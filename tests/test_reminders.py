from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from scheduler.models import ReminderLog
from scheduler.repositories import Repository
from scheduler.services.progress_service import ProgressService
from scheduler.services.reminder_service import ReminderService
from tests.helpers import FakeEmailService


def _seed_goals_for_boundaries(repo: Repository, base: date):
    project = repo.create_project(
        name="Reminder Project",
        deadline=base + timedelta(days=30),
        participants=[("Owner", "owner@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]

    goals = []
    for offset in [4, 3, 1, 0, -1]:
        goals.append(
            repo.add_goal(
                phase_id=phase.id,
                title=f"goal_{offset}",
                owner_participant_id=owner.id,
                milestone_date=base + timedelta(days=offset),
                deadline=base + timedelta(days=10),
                weight=1,
            )
        )
    return goals


def test_milestone_reminder_boundaries(session):
    base = date(2026, 3, 2)
    repo = Repository(session)
    goals = _seed_goals_for_boundaries(repo, base)

    progress_svc = ProgressService(repo)
    for goal in goals:
        progress_svc.record_progress(goal.id, base, 50, updated_by="pm")

    email = FakeEmailService(should_succeed=True)
    svc = ReminderService(repo, email_service=email, near_days=3)
    result = svc.run_milestone_reminders(on_date=base)

    assert result.sent == 3
    assert result.failed == 0
    assert len(email.sent_messages) == 3


def test_overdue_reminders_sent_daily_until_complete(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Overdue Project",
        deadline=base + timedelta(days=30),
        participants=[("Owner", "owner@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="late goal",
        owner_participant_id=owner.id,
        milestone_date=base - timedelta(days=1),
        deadline=base + timedelta(days=1),
        weight=1,
    )

    ProgressService(repo).record_progress(goal.id, base, 60, updated_by="pm")

    email = FakeEmailService(should_succeed=True)
    svc = ReminderService(repo, email_service=email, near_days=3)

    day1 = svc.run_milestone_reminders(on_date=base)
    day2 = svc.run_milestone_reminders(on_date=base + timedelta(days=1))

    assert day1.sent == 1
    assert day2.sent == 1
    assert len(email.sent_messages) == 2

    ProgressService(repo).record_progress(goal.id, base + timedelta(days=1), 100, updated_by="pm")
    day3 = svc.run_milestone_reminders(on_date=base + timedelta(days=2))
    assert day3.sent == 0


def test_reminder_deduplicated_same_day(session):
    base = date(2026, 3, 2)
    repo = Repository(session)

    project = repo.create_project(
        name="Dedup Project",
        deadline=base + timedelta(days=20),
        participants=[("Owner", "owner@example.com")],
    )
    phase = repo.add_phase(project.id, name="P1", objective="Obj")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="goal",
        owner_participant_id=owner.id,
        milestone_date=base + timedelta(days=1),
        deadline=base + timedelta(days=10),
        weight=1,
    )
    ProgressService(repo).record_progress(goal.id, base, 20, updated_by="pm")

    email = FakeEmailService(should_succeed=True)
    svc = ReminderService(repo, email_service=email, near_days=3)

    first = svc.run_milestone_reminders(on_date=base)
    second = svc.run_milestone_reminders(on_date=base)

    assert first.sent == 1
    assert second.skipped == 1
    assert len(email.sent_messages) == 1

    log_count = session.scalar(select(func.count()).select_from(ReminderLog))
    assert log_count == 1
