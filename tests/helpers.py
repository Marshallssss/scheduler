from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from scheduler.repositories import Repository


@dataclass
class FakeEmailService:
    should_succeed: bool = True
    sent_messages: list[tuple[list[str], str, str, str | None]] = field(default_factory=list)

    def send_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        self.sent_messages.append((recipients, subject, body, html_body))
        return self.should_succeed


def seed_basic_project(repo: Repository, base_date: date):
    project = repo.create_project(
        name="Alpha",
        deadline=base_date + timedelta(days=30),
        participants=[("Owner", "owner@example.com"), ("Teammate", "teammate@example.com")],
    )
    phase = repo.add_phase(project.id, name="Phase 1", objective="Deliver MVP")
    owner = repo.list_project_participants(project.id)[0]
    goal = repo.add_goal(
        phase_id=phase.id,
        title="Goal A",
        owner_participant_id=owner.id,
        milestone_date=base_date + timedelta(days=3),
        deadline=base_date + timedelta(days=10),
        weight=1.0,
    )
    return project, phase, goal, owner
