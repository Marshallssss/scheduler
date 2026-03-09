from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from email import policy
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scheduler.repositories import Repository


@dataclass
class FakeEmailService:
    should_succeed: bool = True
    sent_messages: list[tuple[list[str], str, str, str | None]] = field(default_factory=list)
    settings: object = field(default_factory=lambda: type("FakeSettings", (), {"mail_from": ""})())

    def send_email(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        self.sent_messages.append((recipients, subject, body, html_body))
        return self.should_succeed

    def build_email_bytes(
        self,
        recipients: list[str],
        subject: str,
        body: str,
        html_body: str | None = None,
        from_address: str | None = None,
    ) -> bytes:
        if html_body is None:
            msg = MIMEText(body, "plain", "utf-8")
        else:
            msg = MIMEMultipart("alternative")
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        msg["Subject"] = Header(subject, "utf-8").encode()
        if from_address:
            msg["From"] = from_address
        msg["To"] = ", ".join(self.normalize_recipients(recipients))
        msg["X-Unsent"] = "1"
        return msg.as_bytes(policy=policy.SMTP)

    def normalize_recipients(self, recipients: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in recipients if item and item.strip()})


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
