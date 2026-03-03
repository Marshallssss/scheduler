from __future__ import annotations

from datetime import date
from typing import Optional

from scheduler.constants import GOAL_TYPE_ISSUE, GOAL_TYPE_REQUIREMENT, GOAL_TYPES
from scheduler.repositories import Repository


class ProjectService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def create_project(self, name: str, deadline: date, participants: list[tuple[str, str]]):
        if not name.strip():
            raise ValueError("项目名称不能为空")
        if deadline < date.today():
            raise ValueError("项目截止日期不能早于今天")
        if not participants:
            raise ValueError("至少需要 1 位参与者")

        clean_participants: list[tuple[str, str]] = []
        seen_emails: set[str] = set()
        for participant_name, email in participants:
            participant_name = participant_name.strip()
            email = email.strip().lower()
            if not participant_name or not email:
                raise ValueError("参与者姓名和邮箱不能为空")
            if email in seen_emails:
                raise ValueError(f"参与者邮箱重复: {email}")
            seen_emails.add(email)
            clean_participants.append((participant_name, email))

        return self.repo.create_project(name=name.strip(), deadline=deadline, participants=clean_participants)

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
            raise ValueError("goal_type 仅支持 requirement 或 issue")

        normalized_issue_module = issue_module.strip() if issue_module else None

        if normalized_goal_type == GOAL_TYPE_REQUIREMENT:
            if requirement_priority is not None and not (1 <= requirement_priority <= 5):
                raise ValueError("需求优先级必须在 1-5 之间")
            default_weight = float(6 - requirement_priority) if requirement_priority is not None else 1.0
            use_weight = default_weight if weight is None else weight
            use_issue_module = None
            use_issue_total_di = None
        else:
            if issue_total_di is None or issue_total_di <= 0:
                raise ValueError("问题单型目标必须提供大于 0 的总 DI")
            if not normalized_issue_module:
                raise ValueError("问题单型目标必须填写模块")
            use_weight = issue_total_di if weight is None else weight
            use_issue_module = normalized_issue_module
            use_issue_total_di = issue_total_di
            requirement_priority = None

        if use_weight <= 0:
            raise ValueError("权重必须大于 0")

        return self.repo.add_goal(
            phase_id=phase_id,
            title=title.strip(),
            owner_participant_id=owner_participant_id,
            milestone_date=milestone_date,
            deadline=deadline,
            weight=use_weight,
            goal_type=normalized_goal_type,
            requirement_priority=requirement_priority,
            issue_module=use_issue_module,
            issue_total_di=use_issue_total_di,
        )
