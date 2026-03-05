from __future__ import annotations

from datetime import date, timedelta

import pytest

from scheduler.repositories import Repository
from scheduler.services.progress_service import ProgressService
from scheduler.services.project_service import ProjectService


def test_weighted_progress_aggregation(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Weighted Project",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]

    g1 = repo.add_goal(
        phase_id=phase.id,
        title="g1",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
    )
    g2 = repo.add_goal(
        phase_id=phase.id,
        title="g2",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=2),
        deadline=base + timedelta(days=6),
        weight=3,
    )

    svc = ProgressService(repo)
    svc.record_progress(g1.id, base, 50, updated_by="pm")
    svc.record_progress(g2.id, base, 100, updated_by="pm")

    summary = svc.build_project_progress(project.id, base)
    assert summary.progress_percent == 87.5
    assert summary.completed_goals == 1
    assert summary.total_goals == 2


def test_progress_rollback_requires_note(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Rollback",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="g1",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
    )

    svc = ProgressService(repo)
    svc.record_progress(goal.id, base, 80, updated_by="pm")

    with pytest.raises(ValueError, match="回退"):
        svc.record_progress(goal.id, base, 70, updated_by="pm")

    svc.record_progress(goal.id, base, 70, updated_by="pm", note="拆分范围，重估")


def test_progress_rejects_out_of_range(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Range",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="g1",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
    )

    svc = ProgressService(repo)
    with pytest.raises(ValueError, match="0-100"):
        svc.record_progress(goal.id, base, 101, updated_by="pm")


def test_issue_goal_tracks_progress_by_remaining_di(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Issue DI",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="issue-goal",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
        goal_type="issue",
        issue_module="支付",
        issue_total_di=50,
    )

    svc = ProgressService(repo)
    update = svc.record_progress(goal.id, base, progress_percent=None, remaining_di=20, updated_by="pm")
    assert update.progress_percent == 60.0
    assert update.remaining_di == 20

    summary = svc.build_project_progress(project.id, base)
    assert summary.progress_percent == 60.0


def test_issue_goal_remaining_di_increase_requires_note(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Issue rollback",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="issue-goal",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
        goal_type="issue",
        issue_module="订单",
        issue_total_di=30,
    )

    svc = ProgressService(repo)
    svc.record_progress(goal.id, base, progress_percent=None, remaining_di=10, updated_by="pm")

    with pytest.raises(ValueError, match="剩余 DI"):
        svc.record_progress(goal.id, base, progress_percent=None, remaining_di=12, updated_by="pm")

    svc.record_progress(goal.id, base, progress_percent=None, remaining_di=12, updated_by="pm", note="新增问题单")


def test_task_goal_tracks_progress_by_manual_percent(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Task progress",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="task-goal",
        note="跟进合同审批与回签",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=1,
        goal_type="task",
    )

    svc = ProgressService(repo)
    update = svc.record_progress(goal.id, base, progress_percent=42, updated_by="pm")
    assert update.progress_percent == 42.0
    assert update.requirement_total_count is None
    assert update.requirement_done_count is None
    assert update.remaining_di is None

    with pytest.raises(ValueError, match="回退"):
        svc.record_progress(goal.id, base, progress_percent=35, updated_by="pm")

    svc.record_progress(goal.id, base, progress_percent=35, updated_by="pm", note="事务范围重估")


def test_requirement_goal_tracks_progress_by_counts(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Req counts",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="req-goal",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=2,
    )

    svc = ProgressService(repo)
    update = svc.record_progress(
        goal.id,
        base,
        progress_percent=None,
        requirement_total_count=20,
        requirement_done_count=5,
        updated_by="pm",
    )
    assert update.progress_percent == 25.0
    assert update.requirement_total_count == 20
    assert update.requirement_done_count == 5


def test_issue_goal_default_weight_is_not_di(session):
    base = date(2026, 3, 2)
    repo = Repository(session)
    svc = ProjectService(repo)

    project = repo.create_project(
        name="Issue weight",
        deadline=base + timedelta(days=20),
        participants=[("A", "a@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]

    goal = svc.add_goal(
        phase_id=phase.id,
        title="issue-weight",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=5),
        weight=None,
        goal_type="issue",
        issue_module="订单",
        issue_total_di=99,
    )
    assert goal.weight == 1.0
