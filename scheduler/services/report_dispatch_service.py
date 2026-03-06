from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import re
from typing import Optional

from scheduler.config import Settings
from scheduler.constants import REPORT_DAILY, REPORT_MONTHLY, REPORT_PERIODS, REPORT_WEEKLY
from scheduler.repositories import Repository
from scheduler.services.report_service import ReportService, ReportResult
from scheduler.utils import is_last_day_of_month

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class DispatchDueResult:
    period: str
    status: str


class ReportDispatchService:
    def __init__(self, repo: Repository, report_service: ReportService, settings: Settings) -> None:
        self.repo = repo
        self.report_service = report_service
        self.settings = settings

    def list_preferences(self) -> list[dict]:
        self._ensure_preferences()
        order = {REPORT_DAILY: 0, REPORT_WEEKLY: 1, REPORT_MONTHLY: 2}
        items = sorted(
            self.repo.list_report_dispatch_preferences(),
            key=lambda item: (order.get(item.period, 99), item.id),
        )
        return [self._preference_payload(item) for item in items]

    def update_preference(
        self,
        period: str,
        send_time: str,
        recipients: list[str],
        enabled: bool,
    ) -> dict:
        normalized_period = self._normalize_period(period)
        normalized_time = self._normalize_time(send_time)
        normalized_recipients = self._normalize_recipients(recipients)
        item = self.repo.upsert_report_dispatch_preference(
            period=normalized_period,
            send_time=normalized_time,
            recipients_csv=self._serialize_recipients(normalized_recipients),
            enabled=1 if enabled else 0,
        )
        return self._preference_payload(item)

    def preview(self, period: str, run_date: date) -> dict:
        normalized_period = self._normalize_period(period)
        self._ensure_preferences()
        rendered = self.report_service.render_report(period=normalized_period, run_date=run_date)
        default_recipients = sorted(
            {item.email.strip().lower() for item in self.repo.list_all_participants() if item.email and item.email.strip()}
        )
        pref = self.repo.get_report_dispatch_preference(normalized_period)
        scheduled = self._preference_payload(pref) if pref is not None else None
        return {
            "period": normalized_period,
            "run_date": run_date.isoformat(),
            "start_date": rendered.start_date.isoformat(),
            "end_date": rendered.end_date.isoformat(),
            "subject": rendered.subject,
            "markdown": rendered.markdown,
            "default_recipients": default_recipients,
            "scheduled": scheduled,
        }

    def send_now(
        self,
        period: str,
        run_date: date,
        recipients: Optional[list[str]],
        markdown: Optional[str],
        skip_today_schedule: bool,
    ) -> tuple[ReportResult, list[str]]:
        normalized_period = self._normalize_period(period)
        self._ensure_preferences()

        use_recipients: Optional[list[str]] = None
        if recipients is not None:
            normalized_recipients = self._normalize_recipients(recipients)
            if normalized_recipients:
                use_recipients = normalized_recipients

        result = self.report_service.dispatch_report(
            period=normalized_period,
            run_date=run_date,
            recipients=use_recipients,
            markdown=markdown,
        )

        if skip_today_schedule:
            pref = self.repo.get_report_dispatch_preference(normalized_period)
            if pref is not None:
                pref.skip_once_date = date.today()
                pref.updated_at = datetime.utcnow()
                self.repo.session.flush()

        actual_recipients = use_recipients or sorted(
            {item.email.strip().lower() for item in self.repo.list_all_participants() if item.email and item.email.strip()}
        )
        return result, actual_recipients

    def run_due(self, now: datetime) -> list[DispatchDueResult]:
        self._ensure_preferences()
        today = now.date()
        now_time = now.time().replace(second=0, microsecond=0)

        results: list[DispatchDueResult] = []
        for pref in self.repo.list_report_dispatch_preferences():
            if pref.enabled != 1:
                continue
            if not self._is_due_period_day(pref.period, today):
                continue
            if pref.last_scheduled_date == today:
                continue

            if pref.skip_once_date == today:
                pref.last_scheduled_date = today
                pref.last_scheduled_at = now
                pref.last_status = "skipped"
                pref.skip_once_date = None
                pref.updated_at = datetime.utcnow()
                results.append(DispatchDueResult(period=pref.period, status="skipped"))
                continue

            target_time = self._parse_time(pref.send_time)
            if target_time is None or now_time < target_time:
                continue

            recipients = self._deserialize_recipients(pref.recipients_csv)
            result = self.report_service.dispatch_report(
                period=pref.period,
                run_date=today,
                recipients=recipients or None,
                markdown=None,
            )
            pref.last_scheduled_date = today
            pref.last_scheduled_at = now
            pref.last_status = result.status
            pref.updated_at = datetime.utcnow()
            results.append(DispatchDueResult(period=pref.period, status=result.status))

        self.repo.session.flush()
        return results

    def _ensure_preferences(self) -> None:
        defaults = {
            REPORT_DAILY: self._default_time(REPORT_DAILY),
            REPORT_WEEKLY: self._default_time(REPORT_WEEKLY),
            REPORT_MONTHLY: self._default_time(REPORT_MONTHLY),
        }
        for period, send_time in defaults.items():
            self.repo.get_or_create_report_dispatch_preference(period=period, send_time=send_time)
        self.repo.session.flush()

    def _default_time(self, period: str) -> str:
        if period == REPORT_DAILY:
            return self._extract_time(self.settings.daily_report_time, "17:55")
        if period == REPORT_WEEKLY:
            return self._extract_time(self.settings.weekly_report_time, "18:00")
        return self._extract_time(self.settings.monthly_report_time, "18:10")

    def _extract_time(self, raw: str, fallback: str) -> str:
        raw = (raw or "").strip().upper()
        if _TIME_RE.match(raw):
            return raw
        parts = raw.split()
        if parts and _TIME_RE.match(parts[-1]):
            return parts[-1]
        return fallback

    def _normalize_period(self, period: str) -> str:
        normalized = period.strip().lower()
        if normalized not in REPORT_PERIODS:
            raise ValueError("period 仅支持 daily|weekly|monthly")
        return normalized

    def _normalize_time(self, raw: str) -> str:
        value = raw.strip()
        if not _TIME_RE.match(value):
            raise ValueError("send_time 格式错误，应为 HH:MM")
        return value

    def _normalize_recipients(self, recipients: list[str]) -> list[str]:
        return sorted({item.strip().lower() for item in recipients if item and item.strip()})

    def _serialize_recipients(self, recipients: list[str]) -> Optional[str]:
        if not recipients:
            return None
        return ",".join(recipients)

    def _deserialize_recipients(self, raw: Optional[str]) -> list[str]:
        if raw is None or raw.strip() == "":
            return []
        return self._normalize_recipients(raw.split(","))

    def _parse_time(self, value: str) -> Optional[time]:
        if not _TIME_RE.match(value):
            return None
        hour, minute = value.split(":")
        return time(hour=int(hour), minute=int(minute))

    def _is_due_period_day(self, period: str, target_date: date) -> bool:
        if period == REPORT_DAILY:
            return True
        if period == REPORT_WEEKLY:
            return target_date.weekday() == 4
        if period == REPORT_MONTHLY:
            return is_last_day_of_month(target_date)
        return False

    def _preference_payload(self, item) -> dict:
        return {
            "period": item.period,
            "send_time": item.send_time,
            "recipients": self._deserialize_recipients(item.recipients_csv),
            "enabled": bool(item.enabled),
            "skip_once_date": item.skip_once_date.isoformat() if item.skip_once_date is not None else None,
            "last_scheduled_date": item.last_scheduled_date.isoformat() if item.last_scheduled_date is not None else None,
            "last_scheduled_at": item.last_scheduled_at.isoformat() if item.last_scheduled_at is not None else None,
            "last_status": item.last_status,
        }
