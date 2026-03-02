from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections import defaultdict
from typing import Optional

from scheduler.constants import GOAL_STATUS_ACTIVE, GOAL_STATUS_COMPLETED
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
        progress_percent: float,
        updated_by: str,
        note: Optional[str] = None,
    ):
        if progress_percent < 0 or progress_percent > 100:
            raise ValueError("完成率必须在 0-100")

        goal = self.repo.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"目标不存在: {goal_id}")

        latest = self.repo.latest_progress_map([goal_id], update_date).get(goal_id, 0.0)
        if progress_percent < latest and (note is None or not note.strip()):
            raise ValueError("进度回退时必须填写备注")

        update = self.repo.upsert_progress(
            goal_id=goal_id,
            update_date=update_date,
            progress_percent=progress_percent,
            note=note.strip() if note else None,
            updated_by=updated_by,
        )

        goal.status = GOAL_STATUS_COMPLETED if progress_percent >= 100 else GOAL_STATUS_ACTIVE
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
