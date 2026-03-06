from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from scheduler.config import Settings
from scheduler.constants import GOAL_TYPE_ISSUE, GOAL_TYPE_REQUIREMENT, ROLE_ADMIN, ROLE_OWNER
from scheduler.db import create_session_factory, init_db, session_scope
from scheduler.models import Participant, UserAccount
from scheduler.repositories import GoalSnapshot, Repository
from scheduler.services.auth_service import AuthService, AuthClaims
from scheduler.services.email_service import EmailService
from scheduler.services.progress_service import ProgressService
from scheduler.services.report_dispatch_service import ReportDispatchService
from scheduler.services.report_service import ReportService
from scheduler.services.project_service import ProjectService
from scheduler.utils import parse_iso_date, weighted_progress


class ParticipantInput(BaseModel):
    name: str = Field(..., min_length=1)
    email: str = Field(..., min_length=3)


class ProjectCreateInput(BaseModel):
    name: str = Field(..., min_length=1)
    deadline: date
    participants: list[ParticipantInput]


class ProjectUpdateInput(BaseModel):
    name: Optional[str] = None
    deadline: Optional[date] = None
    participants: Optional[list[ParticipantInput]] = None


class PhaseCreateInput(BaseModel):
    project_id: int
    name: str = Field(..., min_length=1)
    objective: str = Field(..., min_length=1)
    order_index: Optional[int] = None


class PhaseUpdateInput(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None
    order_index: Optional[int] = None


class GoalCreateInput(BaseModel):
    phase_id: int
    title: str = Field(..., min_length=1)
    note: Optional[str] = None
    owner_participant_id: int
    milestone_date: date
    deadline: date
    goal_type: str = Field(GOAL_TYPE_REQUIREMENT, min_length=4)
    requirement_priority: Optional[int] = None
    issue_module: Optional[str] = None
    issue_total_di: Optional[float] = None
    weight: Optional[float] = None


class GoalUpdateInput(BaseModel):
    title: Optional[str] = None
    note: Optional[str] = None
    owner_participant_id: Optional[int] = None
    milestone_date: Optional[date] = None
    deadline: Optional[date] = None
    goal_type: Optional[str] = None
    requirement_priority: Optional[int] = None
    issue_module: Optional[str] = None
    issue_total_di: Optional[float] = None
    weight: Optional[float] = None


class ProgressUpdateInput(BaseModel):
    goal_id: int
    date: date
    progress_percent: Optional[float] = None
    remaining_di: Optional[float] = None
    requirement_total_count: Optional[int] = None
    requirement_done_count: Optional[int] = None
    progress_state: str = Field("normal", min_length=4, max_length=20)
    risk_note: Optional[str] = None
    updated_by: str = Field("web_ui", min_length=1)
    note: Optional[str] = None


class ReportSendNowInput(BaseModel):
    period: str = Field(..., min_length=5)
    run_date: Optional[date] = None
    markdown: Optional[str] = None
    recipients: Optional[list[str]] = None
    skip_today_schedule: bool = False


class ReportDispatchPreferenceUpdateInput(BaseModel):
    send_time: str = Field(..., min_length=5, max_length=5)
    recipients: list[str] = Field(default_factory=list)
    enabled: bool = True


class AuthBootstrapInput(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=6)


class AuthLoginInput(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=6)


class UserCreateInput(BaseModel):
    username: str = Field(..., min_length=3, max_length=80)
    password: str = Field(..., min_length=6)
    role: str = Field(..., min_length=4)
    participant_id: Optional[int] = None


def _parse_as_of(raw: Optional[str]) -> date:
    if raw is None or raw.strip() == "":
        return date.today()
    try:
        return parse_iso_date(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式错误，应为 YYYY-MM-DD: {raw}") from exc


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail="未登录")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="认证头格式错误")
    token = authorization[len(prefix) :].strip()
    if not token:
        raise HTTPException(status_code=401, detail="空 token")
    return token


def _serialize_user(user: UserAccount, participant: Optional[Participant]) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "participant_id": user.participant_id,
        "participant_name": participant.name if participant else None,
        "participant_email": participant.email if participant else None,
    }


def _is_admin(user: UserAccount) -> bool:
    return user.role == ROLE_ADMIN


def _goal_is_editable(item: GoalSnapshot, user: UserAccount) -> bool:
    return _is_admin(user) or (
        user.role == ROLE_OWNER and user.participant_id is not None and user.participant_id == item.goal.owner_participant_id
    )


def _can_access_project(repo: Repository, user: UserAccount, project_id: int) -> bool:
    if _is_admin(user):
        return True
    if user.participant_id is None:
        return False
    participants = repo.list_project_participants(project_id)
    participant_ids = {item.id for item in participants}
    return user.participant_id in participant_ids


def _require_auth_user(
    repo: Repository,
    auth_service: AuthService,
    authorization: Optional[str],
) -> tuple[UserAccount, Optional[Participant], AuthClaims]:
    token = _extract_bearer_token(authorization)
    claims = auth_service.parse_token(token)
    if claims is None:
        raise HTTPException(status_code=401, detail="token 无效或已过期")

    user = repo.get_user_account(claims.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    participant = repo.get_participant(user.participant_id) if user.participant_id is not None else None
    return user, participant, claims


def _ensure_admin(user: UserAccount) -> None:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="仅管理员可执行该操作")


def _goal_to_payload(item: GoalSnapshot, user: UserAccount) -> dict:
    return {
        "id": item.goal.id,
        "title": item.goal.title,
        "note": item.goal.note,
        "owner_participant_id": item.owner.id,
        "owner_name": item.owner.name,
        "owner_email": item.owner.email,
        "weight": item.goal.weight,
        "goal_type": item.goal.goal_type,
        "requirement_priority": item.goal.requirement_priority,
        "issue_module": item.goal.issue_module,
        "issue_total_di": item.goal.issue_total_di,
        "milestone_date": item.goal.milestone_date.isoformat(),
        "deadline": item.goal.deadline.isoformat(),
        "status": item.goal.status,
        "progress_percent": item.progress,
        "remaining_di": item.remaining_di,
        "requirement_total_count": item.requirement_total_count,
        "requirement_done_count": item.requirement_done_count,
        "progress_state": item.progress_state,
        "risk_note": item.risk_note,
        "editable": _goal_is_editable(item, user),
    }


def _phase_to_payload(phase) -> dict:
    return {
        "id": phase.id,
        "project_id": phase.project_id,
        "name": phase.name,
        "objective": phase.objective,
        "order_index": phase.order_index,
    }


def _build_report_dispatch_service(repo: Repository, settings: Settings) -> ReportDispatchService:
    email_service = EmailService(settings)
    report_service = ReportService(
        repo=repo,
        email_service=email_service,
        report_output_dir=settings.expanded_report_output_dir,
    )
    return ReportDispatchService(repo=repo, report_service=report_service, settings=settings)


def _project_payload(
    repo: Repository,
    progress_service: ProgressService,
    project_id: int,
    as_of: date,
    user: UserAccount,
) -> dict:
    project = repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    if not _can_access_project(repo, user, project_id):
        raise HTTPException(status_code=403, detail="无权访问该项目")

    participants = repo.list_project_participants(project_id)
    phases = repo.list_phases_by_project(project_id)
    snapshots = repo.list_goal_snapshots_by_project(project_id=project_id, as_of=as_of)

    phase_goals: dict[int, list[GoalSnapshot]] = defaultdict(list)
    for item in snapshots:
        phase_goals[item.phase.id].append(item)

    progress = progress_service.build_project_progress(project_id=project_id, as_of=as_of)
    phase_summary_map = {item.phase_id: item for item in progress.phases}

    phases_payload = []
    for phase in phases:
        goals = sorted(phase_goals.get(phase.id, []), key=lambda item: (item.goal.milestone_date, item.goal.id))
        if phase.id in phase_summary_map:
            phase_summary = phase_summary_map[phase.id]
            summary_payload = {
                "progress_percent": phase_summary.progress_percent,
                "completed_goals": phase_summary.completed_goals,
                "total_goals": phase_summary.total_goals,
            }
        else:
            summary_payload = {
                "progress_percent": 0.0,
                "completed_goals": 0,
                "total_goals": 0,
            }

        phases_payload.append(
            {
                "id": phase.id,
                "name": phase.name,
                "objective": phase.objective,
                "order_index": phase.order_index,
                "summary": summary_payload,
                "goals": [_goal_to_payload(item, user) for item in goals],
            }
        )

    if phases_payload:
        all_goal_values: list[tuple[float, float]] = []
        for phase in phases_payload:
            for goal in phase["goals"]:
                all_goal_values.append((float(goal["progress_percent"]), float(goal["weight"])))
        aggregated_progress = weighted_progress(all_goal_values)
    else:
        aggregated_progress = 0.0

    return {
        "id": project.id,
        "name": project.name,
        "deadline": project.deadline.isoformat(),
        "status": project.status,
        "created_at": project.created_at.isoformat(),
        "summary": {
            "progress_percent": aggregated_progress,
            "completed_goals": progress.completed_goals,
            "total_goals": progress.total_goals,
        },
        "participants": [
            {
                "id": item.id,
                "name": item.name,
                "email": item.email,
            }
            for item in participants
        ],
        "phases": phases_payload,
    }


def create_app(settings: Settings) -> FastAPI:
    init_db(settings)
    session_factory = create_session_factory(settings)
    auth_service = AuthService(settings)
    static_dir = Path(__file__).resolve().parent / "web_static"

    app = FastAPI(title="Project Scheduler Web", version="0.2.0")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/auth/status")
    def auth_status() -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            bootstrapped = repo.count_user_accounts() > 0
            return {
                "bootstrapped": bootstrapped,
                "token_ttl_minutes": settings.auth_token_ttl_minutes,
                "auth_secret_configured": settings.auth_secret != "change-me-please",
            }

    @app.post("/api/auth/bootstrap-admin", status_code=201)
    def bootstrap_admin(payload: AuthBootstrapInput) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            if repo.count_user_accounts() > 0:
                raise HTTPException(status_code=409, detail="系统已初始化账号，不能重复 bootstrap")
            try:
                password_hash = auth_service.hash_password(payload.password)
                user = repo.create_user_account(
                    username=payload.username,
                    password_hash=password_hash,
                    role=ROLE_ADMIN,
                    participant_id=None,
                )
            except (ValueError, IntegrityError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            token = auth_service.issue_token(
                user_id=user.id,
                username=user.username,
                role=user.role,
                participant_id=user.participant_id,
            )
            return {
                "token": token,
                "user": _serialize_user(user, None),
            }

    @app.post("/api/auth/login")
    def login(payload: AuthLoginInput) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user = repo.get_user_by_username(payload.username)
            if user is None:
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            if not auth_service.verify_password(payload.password, user.password_hash):
                raise HTTPException(status_code=401, detail="用户名或密码错误")

            participant = repo.get_participant(user.participant_id) if user.participant_id is not None else None
            token = auth_service.issue_token(
                user_id=user.id,
                username=user.username,
                role=user.role,
                participant_id=user.participant_id,
            )
            return {
                "token": token,
                "user": _serialize_user(user, participant),
            }

    @app.get("/api/auth/me")
    def me(authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, participant, _ = _require_auth_user(repo, auth_service, authorization)
            return {
                "user": _serialize_user(user, participant),
            }

    @app.get("/api/auth/users")
    def list_users(authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)

            users = repo.list_user_accounts()
            participant_ids = [item.participant_id for item in users if item.participant_id is not None]
            participant_map = {
                item.id: item
                for item in repo.get_participants_by_ids([int(pid) for pid in participant_ids if pid is not None])
            }
            payload = []
            for item in users:
                participant = participant_map.get(item.participant_id)
                payload.append(_serialize_user(item, participant))
            return {"users": payload}

    @app.post("/api/auth/users", status_code=201)
    def create_user(payload: UserCreateInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            operator, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(operator)

            role = payload.role.strip().lower()
            participant_id = payload.participant_id
            if role not in {ROLE_ADMIN, ROLE_OWNER}:
                raise HTTPException(status_code=400, detail="role 仅支持 admin 或 owner")

            if role == ROLE_OWNER:
                if participant_id is None:
                    raise HTTPException(status_code=400, detail="owner 角色必须绑定 participant_id")
                participant = repo.get_participant(participant_id)
                if participant is None:
                    raise HTTPException(status_code=400, detail=f"参与者不存在: {participant_id}")
            else:
                participant = None
                participant_id = None

            if repo.get_user_by_username(payload.username) is not None:
                raise HTTPException(status_code=400, detail="用户名已存在")

            try:
                password_hash = auth_service.hash_password(payload.password)
                user = repo.create_user_account(
                    username=payload.username,
                    password_hash=password_hash,
                    role=role,
                    participant_id=participant_id,
                )
            except (ValueError, IntegrityError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            if role == ROLE_OWNER and participant is None and participant_id is not None:
                participant = repo.get_participant(participant_id)

            return {"user": _serialize_user(user, participant)}

    @app.get("/api/participants")
    def list_participants(authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            participants = repo.list_all_participants()
            return {
                "participants": [
                    {
                        "id": item.id,
                        "project_id": item.project_id,
                        "name": item.name,
                        "email": item.email,
                    }
                    for item in participants
                ]
            }

    @app.get("/api/reports/preview")
    def preview_report(
        period: str = Query(..., description="daily|weekly|monthly"),
        run_date: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD"),
        authorization: Optional[str] = Header(None),
    ) -> dict:
        target_date = _parse_as_of(run_date)
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            service = _build_report_dispatch_service(repo, settings)
            try:
                return service.preview(period=period, run_date=target_date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/reports/send-now")
    def send_report_now(payload: ReportSendNowInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            service = _build_report_dispatch_service(repo, settings)
            target_date = payload.run_date if payload.run_date is not None else date.today()
            try:
                result, recipients = service.send_now(
                    period=payload.period,
                    run_date=target_date,
                    recipients=payload.recipients,
                    markdown=payload.markdown,
                    skip_today_schedule=payload.skip_today_schedule,
                )
                preview = service.preview(period=payload.period, run_date=target_date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return {
                "report_id": result.report_id,
                "status": result.status,
                "markdown_path": str(result.markdown_path),
                "subject": preview["subject"],
                "recipients": recipients,
                "skip_today_schedule": payload.skip_today_schedule,
            }

    @app.get("/api/report-dispatch/preferences")
    def list_report_dispatch_preferences(authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            service = _build_report_dispatch_service(repo, settings)
            return {
                "preferences": service.list_preferences(),
            }

    @app.put("/api/report-dispatch/preferences/{period}")
    def update_report_dispatch_preference(
        period: str,
        payload: ReportDispatchPreferenceUpdateInput,
        authorization: Optional[str] = Header(None),
    ) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            service = _build_report_dispatch_service(repo, settings)
            try:
                pref = service.update_preference(
                    period=period,
                    send_time=payload.send_time,
                    recipients=payload.recipients,
                    enabled=payload.enabled,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"preference": pref}

    @app.post("/api/report-dispatch/run-due")
    def run_due_report_dispatch(authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            service = _build_report_dispatch_service(repo, settings)
            runs = service.run_due(now=datetime.now())
            return {
                "runs": [{"period": item.period, "status": item.status} for item in runs],
            }

    @app.get("/api/projects")
    def list_projects(
        as_of: Optional[str] = Query(None, description="YYYY-MM-DD"),
        authorization: Optional[str] = Header(None),
    ) -> dict:
        target_date = _parse_as_of(as_of)
        with session_scope(session_factory) as session:
            repo = Repository(session)
            progress_service = ProgressService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)

            if _is_admin(user):
                projects = repo.list_projects()
            elif user.participant_id is not None:
                projects = repo.list_projects_for_participant(user.participant_id)
            else:
                projects = []

            payload = [_project_payload(repo, progress_service, project.id, target_date, user) for project in projects]
            return {"as_of": target_date.isoformat(), "projects": payload}

    @app.get("/api/projects/{project_id}")
    def get_project(
        project_id: int,
        as_of: Optional[str] = Query(None, description="YYYY-MM-DD"),
        authorization: Optional[str] = Header(None),
    ) -> dict:
        target_date = _parse_as_of(as_of)
        with session_scope(session_factory) as session:
            repo = Repository(session)
            progress_service = ProgressService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            return _project_payload(repo, progress_service, project_id, target_date, user)

    @app.post("/api/projects", status_code=201)
    def create_project(payload: ProjectCreateInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            progress_service = ProgressService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                project = project_service.create_project(
                    name=payload.name,
                    deadline=payload.deadline,
                    participants=[(item.name, item.email) for item in payload.participants],
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return _project_payload(repo, progress_service, project.id, date.today(), user)

    @app.put("/api/projects/{project_id}")
    def update_project(
        project_id: int,
        payload: ProjectUpdateInput,
        authorization: Optional[str] = Header(None),
    ) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            progress_service = ProgressService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                project = project_service.update_project(
                    project_id=project_id,
                    name=payload.name,
                    deadline=payload.deadline,
                    participants=[
                        (item.name, item.email)
                        for item in payload.participants
                    ] if payload.participants is not None else None,
                )
            except (ValueError, IntegrityError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return _project_payload(repo, progress_service, project.id, date.today(), user)

    @app.post("/api/phases", status_code=201)
    def create_phase(payload: PhaseCreateInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                phase = project_service.add_phase(
                    project_id=payload.project_id,
                    name=payload.name,
                    objective=payload.objective,
                    order_index=payload.order_index,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return _phase_to_payload(phase)

    @app.put("/api/phases/{phase_id}")
    def update_phase(
        phase_id: int,
        payload: PhaseUpdateInput,
        authorization: Optional[str] = Header(None),
    ) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                phase = project_service.update_phase(
                    phase_id=phase_id,
                    name=payload.name,
                    objective=payload.objective,
                    order_index=payload.order_index,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return _phase_to_payload(phase)

    @app.delete("/api/phases/{phase_id}", status_code=204, response_class=Response)
    def delete_phase(
        phase_id: int,
        authorization: Optional[str] = Header(None),
    ) -> Response:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                project_service.delete_phase(phase_id=phase_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return Response(status_code=204)

    @app.post("/api/goals", status_code=201)
    def create_goal(payload: GoalCreateInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                goal = project_service.add_goal(
                    phase_id=payload.phase_id,
                    title=payload.title,
                    note=payload.note,
                    owner_participant_id=payload.owner_participant_id,
                    milestone_date=payload.milestone_date,
                    deadline=payload.deadline,
                    weight=payload.weight,
                    goal_type=payload.goal_type,
                    requirement_priority=payload.requirement_priority,
                    issue_module=payload.issue_module,
                    issue_total_di=payload.issue_total_di,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            owner = repo.get_participant(goal.owner_participant_id)
            return {
                "id": goal.id,
                "phase_id": goal.phase_id,
                "title": goal.title,
                "note": goal.note,
                "owner_participant_id": goal.owner_participant_id,
                "owner_name": owner.name if owner else "",
                "owner_email": owner.email if owner else "",
                "weight": goal.weight,
                "goal_type": goal.goal_type,
                "requirement_priority": goal.requirement_priority,
                "issue_module": goal.issue_module,
                "issue_total_di": goal.issue_total_di,
                "milestone_date": goal.milestone_date.isoformat(),
                "deadline": goal.deadline.isoformat(),
                "status": goal.status,
                "progress_percent": 0.0,
                "remaining_di": goal.issue_total_di if goal.goal_type == GOAL_TYPE_ISSUE else None,
                "requirement_total_count": None,
                "requirement_done_count": None,
                "progress_state": "normal",
                "risk_note": None,
            }

    @app.put("/api/goals/{goal_id}")
    def update_goal(
        goal_id: int,
        payload: GoalUpdateInput,
        authorization: Optional[str] = Header(None),
    ) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                goal = project_service.update_goal(
                    goal_id=goal_id,
                    title=payload.title,
                    note=payload.note,
                    owner_participant_id=payload.owner_participant_id,
                    milestone_date=payload.milestone_date,
                    deadline=payload.deadline,
                    weight=payload.weight,
                    goal_type=payload.goal_type,
                    requirement_priority=payload.requirement_priority,
                    issue_module=payload.issue_module,
                    issue_total_di=payload.issue_total_di,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            owner = repo.get_participant(goal.owner_participant_id)
            latest = repo.latest_progress_update(goal.id, date.today())
            return {
                "id": goal.id,
                "phase_id": goal.phase_id,
                "title": goal.title,
                "note": goal.note,
                "owner_participant_id": goal.owner_participant_id,
                "owner_name": owner.name if owner else "",
                "owner_email": owner.email if owner else "",
                "weight": goal.weight,
                "goal_type": goal.goal_type,
                "requirement_priority": goal.requirement_priority,
                "issue_module": goal.issue_module,
                "issue_total_di": goal.issue_total_di,
                "milestone_date": goal.milestone_date.isoformat(),
                "deadline": goal.deadline.isoformat(),
                "status": goal.status,
                "progress_percent": latest.progress_percent if latest is not None else 0.0,
                "remaining_di": latest.remaining_di if latest is not None else goal.issue_total_di,
                "requirement_total_count": latest.requirement_total_count if latest is not None else None,
                "requirement_done_count": latest.requirement_done_count if latest is not None else None,
                "progress_state": latest.progress_state if latest is not None else "normal",
                "risk_note": latest.risk_note if latest is not None else None,
            }

    @app.delete("/api/goals/{goal_id}", status_code=204, response_class=Response)
    def delete_goal(
        goal_id: int,
        authorization: Optional[str] = Header(None),
    ) -> Response:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            project_service = ProjectService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            _ensure_admin(user)
            try:
                project_service.delete_goal(goal_id=goal_id)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return Response(status_code=204)

    @app.post("/api/progress", status_code=201)
    def record_progress(payload: ProgressUpdateInput, authorization: Optional[str] = Header(None)) -> dict:
        with session_scope(session_factory) as session:
            repo = Repository(session)
            progress_service = ProgressService(repo)
            user, _, _ = _require_auth_user(repo, auth_service, authorization)
            goal = repo.get_goal(payload.goal_id)
            if goal is None:
                raise HTTPException(status_code=404, detail=f"目标不存在: {payload.goal_id}")
            phase = repo.get_phase(goal.phase_id)
            if phase is None:
                raise HTTPException(status_code=404, detail=f"阶段不存在: {goal.phase_id}")

            if not _can_access_project(repo, user, phase.project_id):
                raise HTTPException(status_code=403, detail="无权访问该项目")

            if not _is_admin(user):
                if user.participant_id is None or user.participant_id != goal.owner_participant_id:
                    raise HTTPException(status_code=403, detail="负责人只能更新自己负责的目标")

            try:
                update = progress_service.record_progress(
                    goal_id=payload.goal_id,
                    update_date=payload.date,
                    progress_percent=payload.progress_percent,
                    remaining_di=payload.remaining_di,
                    requirement_total_count=payload.requirement_total_count,
                    requirement_done_count=payload.requirement_done_count,
                    progress_state=payload.progress_state,
                    risk_note=payload.risk_note,
                    updated_by=payload.updated_by,
                    note=payload.note,
                )
                project_progress = progress_service.build_project_progress(
                    project_id=phase.project_id,
                    as_of=payload.date,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return {
                "id": update.id,
                "goal_id": update.goal_id,
                "date": update.date.isoformat(),
                "progress_percent": update.progress_percent,
                "remaining_di": update.remaining_di,
                "requirement_total_count": update.requirement_total_count,
                "requirement_done_count": update.requirement_done_count,
                "progress_state": update.progress_state,
                "risk_note": update.risk_note,
                "note": update.note,
                "updated_by": update.updated_by,
                "project_id": phase.project_id,
                "project_progress_percent": project_progress.progress_percent,
            }

    return app
