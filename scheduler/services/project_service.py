from __future__ import annotations

from datetime import date
from typing import Optional

from scheduler.constants import GOAL_TYPE_ISSUE, GOAL_TYPE_REQUIREMENT, GOAL_TYPE_TASK, GOAL_TYPES
from scheduler.repositories import Repository


class ProjectService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def create_project(self, name: str, deadline: date, participants: list[tuple[str, str]]):
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        if deadline < date.today():
            raise ValueError("项目截止日期不能早于今天")

        clean_participants = self._normalize_participants(participants)
        return self.repo.create_project(name=clean_name, deadline=deadline, participants=clean_participants)

    def update_project(
        self,
        project_id: int,
        name: Optional[str] = None,
        deadline: Optional[date] = None,
        participants: Optional[list[tuple[str, str]]] = None,
    ):
        project = self.repo.get_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")

        use_name = project.name
        if name is not None:
            use_name = name.strip()
            if not use_name:
                raise ValueError("项目名称不能为空")

        use_deadline = project.deadline if deadline is None else deadline
        if use_deadline < date.today():
            raise ValueError("项目截止日期不能早于今天")

        goals = self.repo.list_goals_by_project(project_id)
        max_goal_deadline = max((goal.deadline for goal in goals), default=None)
        if max_goal_deadline is not None and use_deadline < max_goal_deadline:
            raise ValueError(f"项目截止日期不能早于现有目标截止日期: {max_goal_deadline.isoformat()}")

        project = self.repo.update_project(project_id=project_id, name=use_name, deadline=use_deadline)

        if participants is not None:
            clean_participants = self._normalize_participants(participants)
            self._sync_project_participants(project_id=project_id, participants=clean_participants)

        self.repo.session.flush()
        return project

    def add_phase(self, project_id: int, name: str, objective: str, order_index: Optional[int] = None):
        project = self.repo.get_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        if not name.strip() or not objective.strip():
            raise ValueError("阶段名称和目标不能为空")

        return self.repo.add_phase(
            project_id=project_id,
            name=name.strip(),
            objective=objective.strip(),
            order_index=order_index,
        )

    def add_goal(
        self,
        phase_id: int,
        title: str,
        owner_participant_id: int,
        milestone_date: date,
        deadline: date,
        weight: Optional[float],
        goal_type: str = GOAL_TYPE_REQUIREMENT,
        requirement_priority: Optional[int] = None,
        issue_module: Optional[str] = None,
        issue_total_di: Optional[float] = None,
        issue_target_di: Optional[float] = None,
        note: Optional[str] = None,
    ):
        return self._create_or_update_goal(
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
            issue_target_di=issue_target_di,
            goal_id=None,
        )

    def update_phase(
        self,
        phase_id: int,
        name: Optional[str] = None,
        objective: Optional[str] = None,
        order_index: Optional[int] = None,
    ):
        phase = self.repo.get_phase(phase_id)
        if phase is None:
            raise ValueError(f"阶段不存在: {phase_id}")

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("阶段名称不能为空")
            phase.name = clean_name
        if objective is not None:
            clean_objective = objective.strip()
            if not clean_objective:
                raise ValueError("阶段目标不能为空")
            phase.objective = clean_objective
        if order_index is not None:
            phase.order_index = order_index

        self.repo.session.flush()
        return phase

    def delete_phase(self, phase_id: int) -> None:
        phase = self.repo.get_phase(phase_id)
        if phase is None:
            raise ValueError(f"阶段不存在: {phase_id}")
        self.repo.session.delete(phase)
        self.repo.session.flush()

    def update_goal(
        self,
        goal_id: int,
        title: Optional[str] = None,
        note: Optional[str] = None,
        owner_participant_id: Optional[int] = None,
        milestone_date: Optional[date] = None,
        deadline: Optional[date] = None,
        weight: Optional[float] = None,
        goal_type: Optional[str] = None,
        requirement_priority: Optional[int] = None,
        issue_module: Optional[str] = None,
        issue_total_di: Optional[float] = None,
        issue_target_di: Optional[float] = None,
    ):
        goal = self.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"目标不存在: {goal_id}")

        use_title = goal.title if title is None else title
        use_note = goal.note if note is None else note
        use_owner_id = goal.owner_participant_id if owner_participant_id is None else owner_participant_id
        use_milestone = goal.milestone_date if milestone_date is None else milestone_date
        use_deadline = goal.deadline if deadline is None else deadline
        use_weight = goal.weight if weight is None else weight
        use_goal_type = goal.goal_type if goal_type is None else goal_type
        use_requirement_priority = goal.requirement_priority if requirement_priority is None else requirement_priority
        use_issue_module = goal.issue_module if issue_module is None else issue_module
        use_issue_total_di = goal.issue_total_di if issue_total_di is None else issue_total_di
        use_issue_target_di = goal.issue_target_di if issue_target_di is None else issue_target_di

        if use_goal_type == GOAL_TYPE_REQUIREMENT:
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None
        if use_goal_type == GOAL_TYPE_ISSUE:
            use_requirement_priority = None
        if use_goal_type == GOAL_TYPE_TASK:
            use_requirement_priority = None
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None

        updated_goal = self._create_or_update_goal(
            phase_id=goal.phase_id,
            title=use_title,
            note=use_note,
            owner_participant_id=use_owner_id,
            milestone_date=use_milestone,
            deadline=use_deadline,
            weight=use_weight,
            goal_type=use_goal_type,
            requirement_priority=use_requirement_priority,
            issue_module=use_issue_module,
            issue_total_di=use_issue_total_di,
            issue_target_di=use_issue_target_di,
            goal_id=goal_id,
        )
        return updated_goal

    def delete_goal(self, goal_id: int) -> None:
        goal = self.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"目标不存在: {goal_id}")
        self.repo.session.delete(goal)
        self.repo.session.flush()

    def _create_or_update_goal(
        self,
        phase_id: int,
        title: str,
        note: Optional[str],
        owner_participant_id: int,
        milestone_date: date,
        deadline: date,
        weight: Optional[float],
        goal_type: str,
        requirement_priority: Optional[int],
        issue_module: Optional[str],
        issue_total_di: Optional[float],
        issue_target_di: Optional[float],
        goal_id: Optional[int],
    ):
        phase = self.repo.get_phase(phase_id)
        if phase is None:
            raise ValueError(f"阶段不存在: {phase_id}")

        project = self.repo.get_project(phase.project_id)
        if project is None:
            raise ValueError(f"项目不存在: {phase.project_id}")

        owner = self.repo.get_participant(owner_participant_id)
        if owner is None:
            raise ValueError(f"负责人不存在: {owner_participant_id}")
        if owner.project_id != project.id:
            raise ValueError("负责人必须是该项目参与者")

        if not title.strip():
            raise ValueError("小目标标题不能为空")
        if milestone_date > deadline:
            raise ValueError("里程碑日期不能晚于小目标截止日期")
        if deadline > project.deadline:
            raise ValueError("小目标截止日期不能晚于项目截止日期")

        normalized_goal_type = goal_type.strip().lower()
        if normalized_goal_type not in GOAL_TYPES:
            raise ValueError("goal_type 仅支持 requirement、issue 或 task")

        normalized_issue_module = issue_module.strip() if issue_module else None

        if normalized_goal_type == GOAL_TYPE_REQUIREMENT:
            if requirement_priority is not None and not (1 <= requirement_priority <= 5):
                raise ValueError("需求优先级必须在 1-5 之间")
            default_weight = float(6 - requirement_priority) if requirement_priority is not None else 1.0
            use_weight = default_weight if weight is None else weight
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None
        elif normalized_goal_type == GOAL_TYPE_ISSUE:
            if issue_total_di is None or issue_total_di <= 0:
                raise ValueError("问题单型目标必须提供大于 0 的总 DI")
            if not normalized_issue_module:
                raise ValueError("问题单型目标必须填写模块")
            normalized_issue_target_di = 0.0 if issue_target_di is None else float(issue_target_di)
            if normalized_issue_target_di < 0:
                raise ValueError("问题单目标 DI 不能小于 0")
            if normalized_issue_target_di >= issue_total_di:
                raise ValueError("问题单目标 DI 必须小于总 DI")
            use_weight = 1.0 if weight is None else weight
            use_issue_module = normalized_issue_module
            use_issue_total_di = issue_total_di
            use_issue_target_di = normalized_issue_target_di
            requirement_priority = None
        else:
            if note is None or not note.strip():
                raise ValueError("事务型目标必须填写备注，明确事务内容")
            use_weight = 1.0 if weight is None else weight
            requirement_priority = None
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None

        if use_weight <= 0:
            raise ValueError("权重必须大于 0")

        clean_note = note.strip() if note else None

        if goal_id is None:
            return self.repo.add_goal(
                phase_id=phase_id,
                title=title.strip(),
                note=clean_note,
                owner_participant_id=owner_participant_id,
                milestone_date=milestone_date,
                deadline=deadline,
                weight=use_weight,
                goal_type=normalized_goal_type,
                requirement_priority=requirement_priority,
                issue_module=use_issue_module,
                issue_total_di=use_issue_total_di,
                issue_target_di=use_issue_target_di,
            )

        goal = self.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"目标不存在: {goal_id}")
        goal.title = title.strip()
        goal.note = clean_note
        goal.owner_participant_id = owner_participant_id
        goal.milestone_date = milestone_date
        goal.deadline = deadline
        goal.weight = use_weight
        goal.goal_type = normalized_goal_type
        goal.requirement_priority = requirement_priority
        goal.issue_module = use_issue_module
        goal.issue_total_di = use_issue_total_di
        goal.issue_target_di = use_issue_target_di
        self.repo.session.flush()
        return goal

    def _normalize_participants(self, participants: list[tuple[str, str]]) -> list[tuple[str, str]]:
        if not participants:
            raise ValueError("至少需要 1 位参与者")

        clean_participants: list[tuple[str, str]] = []
        seen_emails: set[str] = set()
        for participant_name, email in participants:
            clean_name = participant_name.strip()
            clean_email = email.strip().lower()
            if not clean_name or not clean_email:
                raise ValueError("参与者姓名和邮箱不能为空")
            if clean_email in seen_emails:
                raise ValueError(f"参与者邮箱重复: {clean_email}")
            seen_emails.add(clean_email)
            clean_participants.append((clean_name, clean_email))
        return clean_participants

    def _sync_project_participants(self, project_id: int, participants: list[tuple[str, str]]) -> None:
        existing = self.repo.list_project_participants(project_id)
        existing_by_email = {item.email.lower(): item for item in existing}
        target_emails = {email for _, email in participants}

        for name, email in participants:
            participant = existing_by_email.get(email)
            if participant is None:
                self.repo.add_participant(project_id=project_id, name=name, email=email)
                continue
            participant.name = name

        for participant in existing:
            email = participant.email.lower()
            if email in target_emails:
                continue
            if self.repo.participant_has_owned_goals(participant.id):
                raise ValueError(f"参与者无法移除（存在负责人目标）: {participant.name} <{participant.email}>")
            if self.repo.participant_has_user_account(participant.id):
                raise ValueError(f"参与者无法移除（已绑定账号）: {participant.name} <{participant.email}>")
            self.repo.delete_participant(participant.id)
