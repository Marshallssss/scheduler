from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from scheduler.constants import PROJECT_STATUS_ACTIVE
from scheduler.models import (
    Goal,
    GoalProgressUpdate,
    Participant,
    Phase,
    Project,
    ReminderLog,
    ReportRecord,
    UserAccount,
)


@dataclass
class GoalSnapshot:
    goal: Goal
    project: Project
    phase: Phase
    owner: Participant
    progress: float
    remaining_di: Optional[float]
    requirement_total_count: Optional[int]
    requirement_done_count: Optional[int]


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_project(self, name: str, deadline: date, participants: list[tuple[str, str]]) -> Project:
        project = Project(name=name, deadline=deadline, status=PROJECT_STATUS_ACTIVE)
        self.session.add(project)
        self.session.flush()

        for participant_name, email in participants:
            participant = Participant(project_id=project.id, name=participant_name, email=email)
            self.session.add(participant)

        self.session.flush()
        return project

    def get_project(self, project_id: int) -> Optional[Project]:
        return self.session.get(Project, project_id)

    def update_project(self, project_id: int, name: str, deadline: date) -> Project:
        project = self.get_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        project.name = name
        project.deadline = deadline
        self.session.flush()
        return project

    def list_projects(self) -> list[Project]:
        stmt = select(Project).order_by(Project.id.asc())
        return list(self.session.scalars(stmt))

    def list_projects_for_participant(self, participant_id: int) -> list[Project]:
        stmt = (
            select(Project)
            .join(Participant, Participant.project_id == Project.id)
            .where(Participant.id == participant_id)
            .order_by(Project.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_project_participants(self, project_id: int) -> list[Participant]:
        stmt = select(Participant).where(Participant.project_id == project_id).order_by(Participant.id.asc())
        return list(self.session.scalars(stmt))

    def list_phases_by_project(self, project_id: int) -> list[Phase]:
        stmt = select(Phase).where(Phase.project_id == project_id).order_by(Phase.order_index.asc(), Phase.id.asc())
        return list(self.session.scalars(stmt))

    def list_all_participants(self) -> list[Participant]:
        stmt = select(Participant).order_by(Participant.id.asc())
        return list(self.session.scalars(stmt))

    def get_participants_by_ids(self, participant_ids: list[int]) -> list[Participant]:
        if not participant_ids:
            return []
        stmt = select(Participant).where(Participant.id.in_(participant_ids)).order_by(Participant.id.asc())
        return list(self.session.scalars(stmt))

    def add_participant(self, project_id: int, name: str, email: str) -> Participant:
        participant = Participant(project_id=project_id, name=name, email=email)
        self.session.add(participant)
        self.session.flush()
        return participant

    def delete_participant(self, participant_id: int) -> None:
        participant = self.get_participant(participant_id)
        if participant is None:
            return
        self.session.delete(participant)
        self.session.flush()

    def participant_has_owned_goals(self, participant_id: int) -> bool:
        stmt = select(Goal.id).where(Goal.owner_participant_id == participant_id).limit(1)
        return self.session.scalar(stmt) is not None

    def participant_has_user_account(self, participant_id: int) -> bool:
        stmt = select(UserAccount.id).where(UserAccount.participant_id == participant_id).limit(1)
        return self.session.scalar(stmt) is not None

    def add_phase(
        self,
        project_id: int,
        name: str,
        objective: str,
        order_index: Optional[int] = None,
    ) -> Phase:
        if order_index is None:
            stmt = select(func.max(Phase.order_index)).where(Phase.project_id == project_id)
            max_order = self.session.scalar(stmt)
            order_index = (max_order or 0) + 1

        phase = Phase(project_id=project_id, name=name, objective=objective, order_index=order_index)
        self.session.add(phase)
        self.session.flush()
        return phase

    def get_phase(self, phase_id: int) -> Optional[Phase]:
        return self.session.get(Phase, phase_id)

    def add_goal(
        self,
        phase_id: int,
        title: str,
        owner_participant_id: int,
        milestone_date: date,
        deadline: date,
        weight: float = 1.0,
        goal_type: str = "requirement",
        requirement_priority: Optional[int] = None,
        issue_module: Optional[str] = None,
        issue_total_di: Optional[float] = None,
        note: Optional[str] = None,
    ) -> Goal:
        goal = Goal(
            phase_id=phase_id,
            title=title,
            note=note,
            owner_participant_id=owner_participant_id,
            milestone_date=milestone_date,
            deadline=deadline,
            weight=weight,
            goal_type=goal_type,
            requirement_priority=requirement_priority,
            issue_module=issue_module,
            issue_total_di=issue_total_di,
            status="active",
        )
        self.session.add(goal)
        self.session.flush()
        return goal

    def list_goals_by_project(self, project_id: int) -> list[Goal]:
        stmt = (
            select(Goal)
            .join(Phase, Goal.phase_id == Phase.id)
            .where(Phase.project_id == project_id)
            .order_by(Phase.order_index.asc(), Goal.id.asc())
        )
        return list(self.session.scalars(stmt))

    def list_goal_snapshots_by_project(self, project_id: int, as_of: date) -> list[GoalSnapshot]:
        goals = self.list_goals_by_project(project_id)
        progress_state_map = self.latest_progress_state_map([goal.id for goal in goals], as_of)

        phase_map = {phase.id: phase for phase in self.session.scalars(select(Phase).where(Phase.project_id == project_id))}
        project = self.get_project(project_id)
        owner_ids = {goal.owner_participant_id for goal in goals}
        owner_map = {
            owner.id: owner
            for owner in self.session.scalars(select(Participant).where(Participant.id.in_(owner_ids)))
        } if owner_ids else {}

        snapshots: list[GoalSnapshot] = []
        if project is None:
            return snapshots

        for goal in goals:
            progress_state = progress_state_map.get(goal.id)
            snapshots.append(
                GoalSnapshot(
                    goal=goal,
                    project=project,
                    phase=phase_map[goal.phase_id],
                    owner=owner_map[goal.owner_participant_id],
                    progress=progress_state["progress_percent"] if progress_state else 0.0,
                    remaining_di=progress_state["remaining_di"] if progress_state else None,
                    requirement_total_count=progress_state["requirement_total_count"] if progress_state else None,
                    requirement_done_count=progress_state["requirement_done_count"] if progress_state else None,
                )
            )
        return snapshots

    def list_all_goal_snapshots(self, as_of: date) -> list[GoalSnapshot]:
        stmt: Select[tuple[Goal, Phase, Project, Participant]] = (
            select(Goal, Phase, Project, Participant)
            .join(Phase, Goal.phase_id == Phase.id)
            .join(Project, Phase.project_id == Project.id)
            .join(Participant, Goal.owner_participant_id == Participant.id)
            .where(Project.status == PROJECT_STATUS_ACTIVE)
            .order_by(Project.id.asc(), Phase.order_index.asc(), Goal.id.asc())
        )
        rows = self.session.execute(stmt).all()
        if not rows:
            return []
        goal_ids = [row[0].id for row in rows]
        progress_state_map = self.latest_progress_state_map(goal_ids, as_of)
        snapshots: list[GoalSnapshot] = []
        for goal, phase, project, owner in rows:
            progress_state = progress_state_map.get(goal.id)
            snapshots.append(
                GoalSnapshot(
                    goal=goal,
                    phase=phase,
                    project=project,
                    owner=owner,
                    progress=progress_state["progress_percent"] if progress_state else 0.0,
                    remaining_di=progress_state["remaining_di"] if progress_state else None,
                    requirement_total_count=progress_state["requirement_total_count"] if progress_state else None,
                    requirement_done_count=progress_state["requirement_done_count"] if progress_state else None,
                )
            )
        return snapshots

    def latest_progress_state_map(self, goal_ids: list[int], as_of: date) -> dict[int, dict[str, Optional[float]]]:
        if not goal_ids:
            return {}

        latest_dates_subq = (
            select(GoalProgressUpdate.goal_id, func.max(GoalProgressUpdate.date).label("latest_date"))
            .where(and_(GoalProgressUpdate.goal_id.in_(goal_ids), GoalProgressUpdate.date <= as_of))
            .group_by(GoalProgressUpdate.goal_id)
            .subquery()
        )

        stmt = (
            select(
                GoalProgressUpdate.goal_id,
                GoalProgressUpdate.progress_percent,
                GoalProgressUpdate.remaining_di,
                GoalProgressUpdate.requirement_total_count,
                GoalProgressUpdate.requirement_done_count,
            )
            .join(
                latest_dates_subq,
                and_(
                    GoalProgressUpdate.goal_id == latest_dates_subq.c.goal_id,
                    GoalProgressUpdate.date == latest_dates_subq.c.latest_date,
                ),
            )
        )

        return {
            goal_id: {
                "progress_percent": float(progress),
                "remaining_di": remaining_di,
                "requirement_total_count": requirement_total_count,
                "requirement_done_count": requirement_done_count,
            }
            for goal_id, progress, remaining_di, requirement_total_count, requirement_done_count in self.session.execute(stmt).all()
        }

    def latest_progress_map(self, goal_ids: list[int], as_of: date) -> dict[int, float]:
        state_map = self.latest_progress_state_map(goal_ids, as_of)
        return {goal_id: float(value["progress_percent"] or 0.0) for goal_id, value in state_map.items()}

    def upsert_progress(
        self,
        goal_id: int,
        update_date: date,
        progress_percent: float,
        note: Optional[str],
        updated_by: str,
        remaining_di: Optional[float] = None,
        requirement_total_count: Optional[int] = None,
        requirement_done_count: Optional[int] = None,
    ) -> GoalProgressUpdate:
        stmt = select(GoalProgressUpdate).where(
            and_(GoalProgressUpdate.goal_id == goal_id, GoalProgressUpdate.date == update_date)
        )
        existing = self.session.scalar(stmt)
        if existing is None:
            existing = GoalProgressUpdate(
                goal_id=goal_id,
                date=update_date,
                progress_percent=progress_percent,
                remaining_di=remaining_di,
                requirement_total_count=requirement_total_count,
                requirement_done_count=requirement_done_count,
                note=note,
                updated_by=updated_by,
            )
            self.session.add(existing)
        else:
            existing.progress_percent = progress_percent
            existing.remaining_di = remaining_di
            existing.requirement_total_count = requirement_total_count
            existing.requirement_done_count = requirement_done_count
            existing.note = note
            existing.updated_by = updated_by
            existing.created_at = datetime.utcnow()

        self.session.flush()
        return existing

    def has_reminder(self, goal_id: int, reminder_date: date, reminder_type: str, recipient: str) -> bool:
        stmt = select(ReminderLog.id).where(
            and_(
                ReminderLog.goal_id == goal_id,
                ReminderLog.date == reminder_date,
                ReminderLog.reminder_type == reminder_type,
                ReminderLog.recipient == recipient,
            )
        )
        return self.session.scalar(stmt) is not None

    def log_reminder(
        self,
        goal_id: int,
        reminder_date: date,
        reminder_type: str,
        recipient: str,
        status: str,
    ) -> ReminderLog:
        item = ReminderLog(
            goal_id=goal_id,
            date=reminder_date,
            reminder_type=reminder_type,
            recipient=recipient,
            status=status,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def create_report_record(
        self,
        period: str,
        period_start: date,
        period_end: date,
        markdown_path: str,
        status: str,
    ) -> ReportRecord:
        record = ReportRecord(
            period=period,
            period_start=period_start,
            period_end=period_end,
            markdown_path=markdown_path,
            status=status,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def mark_report_emailed(self, report_id: int, status: str) -> None:
        record = self.session.get(ReportRecord, report_id)
        if record is None:
            return
        record.status = status
        record.emailed_at = datetime.utcnow()

    def grouped_goal_snapshots_by_project(self, as_of: date) -> dict[int, list[GoalSnapshot]]:
        grouped: dict[int, list[GoalSnapshot]] = defaultdict(list)
        for snapshot in self.list_all_goal_snapshots(as_of=as_of):
            grouped[snapshot.project.id].append(snapshot)
        return grouped

    def list_progress_updates_between(self, start_date: date, end_date: date) -> list[GoalProgressUpdate]:
        stmt = (
            select(GoalProgressUpdate)
            .where(and_(GoalProgressUpdate.date >= start_date, GoalProgressUpdate.date <= end_date))
            .order_by(GoalProgressUpdate.date.asc(), GoalProgressUpdate.goal_id.asc())
        )
        return list(self.session.scalars(stmt))

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        return self.session.get(Goal, goal_id)

    def get_participant(self, participant_id: int) -> Optional[Participant]:
        return self.session.get(Participant, participant_id)

    def has_progress_update(self, goal_id: int, update_date: date) -> bool:
        stmt = select(GoalProgressUpdate.id).where(
            and_(GoalProgressUpdate.goal_id == goal_id, GoalProgressUpdate.date == update_date)
        )
        return self.session.scalar(stmt) is not None

    def latest_progress_update(self, goal_id: int, as_of: date) -> Optional[GoalProgressUpdate]:
        stmt = (
            select(GoalProgressUpdate)
            .where(and_(GoalProgressUpdate.goal_id == goal_id, GoalProgressUpdate.date <= as_of))
            .order_by(GoalProgressUpdate.date.desc(), GoalProgressUpdate.created_at.desc(), GoalProgressUpdate.id.desc())
        )
        return self.session.scalars(stmt).first()

    def count_user_accounts(self) -> int:
        stmt = select(func.count()).select_from(UserAccount)
        count = self.session.scalar(stmt)
        return int(count or 0)

    def create_user_account(
        self,
        username: str,
        password_hash: str,
        role: str,
        participant_id: Optional[int],
    ) -> UserAccount:
        user = UserAccount(
            username=username.strip().lower(),
            password_hash=password_hash,
            role=role,
            participant_id=participant_id,
        )
        self.session.add(user)
        self.session.flush()
        return user

    def get_user_by_username(self, username: str) -> Optional[UserAccount]:
        stmt = select(UserAccount).where(UserAccount.username == username.strip().lower())
        return self.session.scalar(stmt)

    def get_user_account(self, user_id: int) -> Optional[UserAccount]:
        return self.session.get(UserAccount, user_id)

    def list_user_accounts(self) -> list[UserAccount]:
        stmt = select(UserAccount).order_by(UserAccount.id.asc())
        return list(self.session.scalars(stmt))
