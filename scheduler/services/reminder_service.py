from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from scheduler.constants import (
    EMAIL_STATUS_FAILED,
    EMAIL_STATUS_SENT,
    REMINDER_MISSING_UPDATE,
    REMINDER_NEAR,
    REMINDER_OVERDUE,
)
from scheduler.repositories import GoalSnapshot, Repository
from scheduler.services.email_service import EmailService


@dataclass
class ReminderRunResult:
    sent: int = 0
    failed: int = 0
    skipped: int = 0


class ReminderService:
    def __init__(self, repo: Repository, email_service: EmailService, near_days: int) -> None:
        self.repo = repo
        self.email_service = email_service
        self.near_days = near_days

    def run_milestone_reminders(self, on_date: date) -> ReminderRunResult:
        result = ReminderRunResult()
        snapshots = self.repo.list_all_goal_snapshots(as_of=on_date)

        for item in snapshots:
            if item.progress >= 100:
                continue

            delta = (item.goal.milestone_date - on_date).days
            reminder_type: Optional[str] = None
            if 0 < delta <= self.near_days:
                reminder_type = REMINDER_NEAR
            elif delta < 0:
                reminder_type = REMINDER_OVERDUE

            if reminder_type is None:
                continue

            status, was_skipped = self._send_goal_reminder(
                item=item,
                on_date=on_date,
                reminder_type=reminder_type,
            )
            if was_skipped:
                result.skipped += 1
            elif status == EMAIL_STATUS_SENT:
                result.sent += 1
            else:
                result.failed += 1

        return result

    def run_missing_progress_nudges(self, on_date: date) -> ReminderRunResult:
        result = ReminderRunResult()
        snapshots = self.repo.list_all_goal_snapshots(as_of=on_date)

        for item in snapshots:
            if item.progress >= 100:
                continue
            if self.repo.has_progress_update(item.goal.id, on_date):
                continue

            status, was_skipped = self._send_goal_reminder(
                item=item,
                on_date=on_date,
                reminder_type=REMINDER_MISSING_UPDATE,
            )
            if was_skipped:
                result.skipped += 1
            elif status == EMAIL_STATUS_SENT:
                result.sent += 1
            else:
                result.failed += 1

        return result

    def _send_goal_reminder(
        self,
        item: GoalSnapshot,
        on_date: date,
        reminder_type: str,
    ) -> tuple[str, bool]:
        recipient = item.owner.email
        if self.repo.has_reminder(item.goal.id, on_date, reminder_type, recipient):
            return EMAIL_STATUS_SENT, True

        subject, body = self._build_message(item, on_date=on_date, reminder_type=reminder_type)
        ok = self.email_service.send_email([recipient], subject, body)
        status = EMAIL_STATUS_SENT if ok else EMAIL_STATUS_FAILED
        self.repo.log_reminder(
            goal_id=item.goal.id,
            reminder_date=on_date,
            reminder_type=reminder_type,
            recipient=recipient,
            status=status,
        )
        return status, False

    def _build_message(self, item: GoalSnapshot, on_date: date, reminder_type: str) -> tuple[str, str]:
        if reminder_type == REMINDER_NEAR:
            subject = f"[里程碑临近] {item.project.name} / {item.goal.title}"
            headline = "里程碑即将到期"
        elif reminder_type == REMINDER_OVERDUE:
            subject = f"[里程碑逾期] {item.project.name} / {item.goal.title}"
            headline = "里程碑已逾期，请尽快更新"
        else:
            subject = f"[进度催报] {item.project.name} / {item.goal.title}"
            headline = "今日尚未提交进度，请在收工前更新"

        body = (
            f"{headline}\n\n"
            f"日期: {on_date.isoformat()}\n"
            f"项目: {item.project.name}\n"
            f"阶段: {item.phase.name}\n"
            f"目标: {item.goal.title}\n"
            f"负责人: {item.owner.name} <{item.owner.email}>\n"
            f"当前完成率: {item.progress:.2f}%\n"
            f"里程碑日期: {item.goal.milestone_date.isoformat()}\n"
            f"目标截止日期: {item.goal.deadline.isoformat()}\n"
        )
        return subject, body
