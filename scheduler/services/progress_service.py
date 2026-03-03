from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections import defaultdict
from typing import Optional

from scheduler.constants import GOAL_STATUS_ACTIVE, GOAL_STATUS_COMPLETED, GOAL_TYPE_ISSUE
from scheduler.repositories import GoalSnapshot, Repository
from scheduler.utils import weighted_progress


@dataclass
class PhaseProgress:
    phase_id: int
    phase_name: str
    progress_percent: float
    total_goals: int
    completed_goals: int


@dataclass
class ProjectProgress:
    project_id: int
    project_name: str
    progress_percent: float
    total_goals: int
    completed_goals: int
    phases: list[PhaseProgress]


class ProgressService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def record_progress(
        self,
        goal_id: int,
        update_date: date,
        progress_percent: Optional[float],
        updated_by: str,
        note: Optional[str] = None,
        remaining_di: Optional[float] = None,
        requirement_total_count: Optional[int] = None,
        requirement_done_count: Optional[int] = None,
    ):
        goal = self.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"目标不存在: {goal_id}")

        clean_note = note.strip() if note else None
        latest = self.repo.latest_progress_update(goal_id, update_date)

        if goal.goal_type == GOAL_TYPE_ISSUE:
            if goal.issue_total_di is None or goal.issue_total_di <= 0:
                raise ValueError("问题单型目标缺少总 DI，无法计算进度")

            if remaining_di is None:
                if progress_percent is None:
                    raise ValueError("问题单型目标必须填写剩余 DI")
                if progress_percent < 0 or progress_percent > 100:
                    raise ValueError("完成率必须在 0-100")
                remaining_di = round((100 - progress_percent) * goal.issue_total_di / 100, 2)

            if remaining_di < 0:
                raise ValueError("剩余 DI 不能小于 0")

            latest_remaining = latest.remaining_di if latest and latest.remaining_di is not None else goal.issue_total_di
            if remaining_di > latest_remaining and clean_note is None:
                raise ValueError("剩余 DI 增加时必须填写备注")

            computed_progress = round(max(0.0, min(100.0, (goal.issue_total_di - remaining_di) * 100 / goal.issue_total_di)), 2)
            requirement_total_count = None
            requirement_done_count = None
        else:
            if requirement_total_count is not None or requirement_done_count is not None:
                if requirement_total_count is None or requirement_done_count is None:
                    raise ValueError("需求型目标需同时填写总需求数和已完成需求数")
                if requirement_total_count < 0:
                    raise ValueError("总需求数不能小于 0")
                if requirement_done_count < 0:
                    raise ValueError("已完成需求数不能小于 0")
                if requirement_done_count > requirement_total_count:
                    raise ValueError("已完成需求数不能大于总需求数")
                if requirement_total_count == 0:
                    computed_progress = 0.0
                else:
                    computed_progress = round(requirement_done_count * 100 / requirement_total_count, 2)
            else:
                if progress_percent is None:
                    raise ValueError("需求型目标必须填写总需求数/已完成需求数，或直接填写完成率")
                if progress_percent < 0 or progress_percent > 100:
                    raise ValueError("完成率必须在 0-100")
                computed_progress = float(progress_percent)
                requirement_total_count = None
                requirement_done_count = None

            latest_progress = latest.progress_percent if latest is not None else 0.0
            if computed_progress < latest_progress and clean_note is None:
                raise ValueError("进度回退时必须填写备注")

            remaining_di = None

        update = self.repo.upsert_progress(
            goal_id=goal_id,
            update_date=update_date,
            progress_percent=computed_progress,
            remaining_di=remaining_di,
            requirement_total_count=requirement_total_count,
            requirement_done_count=requirement_done_count,
            note=clean_note,
            updated_by=updated_by,
        )

        goal.status = GOAL_STATUS_COMPLETED if computed_progress >= 100 else GOAL_STATUS_ACTIVE
        return update

    def build_project_progress(self, project_id: int, as_of: date) -> ProjectProgress:
        snapshots = self.repo.list_goal_snapshots_by_project(project_id=project_id, as_of=as_of)
        project = self.repo.get_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")

        phase_groups: dict[int, list[GoalSnapshot]] = defaultdict(list)
        for item in snapshots:
            phase_groups[item.phase.id].append(item)

        phase_progresses: list[PhaseProgress] = []
        weighted_values: list[tuple[float, float]] = []
        completed_goals = 0

        for phase_id, goals in phase_groups.items():
            phase_weighted_values = [(goal.progress, goal.goal.weight) for goal in goals]
            phase_progress = weighted_progress(phase_weighted_values)
            phase_completed = sum(1 for goal in goals if goal.progress >= 100)
            completed_goals += phase_completed

            phase_progresses.append(
                PhaseProgress(
                    phase_id=phase_id,
                    phase_name=goals[0].phase.name,
                    progress_percent=phase_progress,
                    total_goals=len(goals),
                    completed_goals=phase_completed,
                )
            )
            weighted_values.extend(phase_weighted_values)

        phase_progresses.sort(key=lambda item: item.phase_id)
        overall = weighted_progress(weighted_values)
        return ProjectProgress(
            project_id=project.id,
            project_name=project.name,
            progress_percent=overall,
            total_goals=len(snapshots),
            completed_goals=completed_goals,
            phases=phase_progresses,
        )

    def build_all_projects_progress(self, as_of: date) -> list[ProjectProgress]:
        projects = self.repo.list_projects()
        return [self.build_project_progress(project.id, as_of=as_of) for project in projects]
