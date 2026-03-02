from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from scheduler.constants import (
    EMAIL_STATUS_FAILED,
    EMAIL_STATUS_SENT,
    REPORT_DAILY,
    REPORT_MONTHLY,
    REPORT_PERIODS,
    REPORT_WEEKLY,
)
from scheduler.repositories import GoalSnapshot, Repository
from scheduler.services.email_service import EmailService
from scheduler.utils import month_range, week_range, weighted_progress


@dataclass
class ReportResult:
    markdown_path: Path
    status: str
    report_id: int


class ReportService:
    def __init__(self, repo: Repository, email_service: EmailService, report_output_dir: Path) -> None:
        self.repo = repo
        self.email_service = email_service
        self.report_output_dir = report_output_dir

        templates_dir = Path(__file__).resolve().parent.parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def period_window(self, period: str, run_date: date) -> tuple[date, date]:
        if period == REPORT_DAILY:
            return run_date, run_date
        if period == REPORT_WEEKLY:
            return week_range(run_date)
        if period == REPORT_MONTHLY:
            return month_range(run_date)
        raise ValueError(f"不支持的报表周期: {period}")

    def generate_report(self, period: str, run_date: date) -> ReportResult:
        if period not in REPORT_PERIODS:
            raise ValueError(f"不支持的报表周期: {period}")

        start_date, end_date = self.period_window(period, run_date)
        content = self._render_markdown(period=period, start_date=start_date, end_date=end_date, as_of=end_date)

        self.report_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = self.report_output_dir / f"{period}_{start_date}_{end_date}_{timestamp}.md"
        file_path.write_text(content, encoding="utf-8")

        record = self.repo.create_report_record(
            period=period,
            period_start=start_date,
            period_end=end_date,
            markdown_path=str(file_path),
            status="generated",
        )

        recipients = sorted({participant.email for participant in self.repo.list_all_participants()})
        subject = self._subject(period, start_date, end_date)
        sent = self.email_service.send_email(recipients, subject, content)
        status = EMAIL_STATUS_SENT if sent else EMAIL_STATUS_FAILED
        self.repo.mark_report_emailed(record.id, status=status)

        return ReportResult(markdown_path=file_path, status=status, report_id=record.id)

    def _subject(self, period: str, start_date: date, end_date: date) -> str:
        labels = {
            REPORT_DAILY: "日报",
            REPORT_WEEKLY: "周报",
            REPORT_MONTHLY: "月报",
        }
        return f"[项目{labels[period]}] {start_date.isoformat()} ~ {end_date.isoformat()}"

    def _render_markdown(self, period: str, start_date: date, end_date: date, as_of: date) -> str:
        template = self.env.get_template(f"{period}_report.md.j2")
        grouped = self.repo.grouped_goal_snapshots_by_project(as_of=as_of)
        projects_context = [self._project_context(items) for _, items in sorted(grouped.items(), key=lambda x: x[0])]

        updates = self.repo.list_progress_updates_between(start_date, end_date)
        rollback_count = sum(1 for update in updates if (update.note or "").strip())

        return template.render(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            period=period,
            start_date=start_date,
            end_date=end_date,
            projects=projects_context,
            update_count=len(updates),
            rollback_count=rollback_count,
        )

    def _project_context(self, snapshots: list[GoalSnapshot]) -> dict:
        project = snapshots[0].project
        weighted_values = [(item.progress, item.goal.weight) for item in snapshots]
        overall_progress = weighted_progress(weighted_values)

        phase_map: dict[int, list[GoalSnapshot]] = defaultdict(list)
        for item in snapshots:
            phase_map[item.phase.id].append(item)

        phases = []
        for phase_id, items in sorted(phase_map.items(), key=lambda pair: pair[0]):
            phase_progress = weighted_progress([(it.progress, it.goal.weight) for it in items])
            phases.append(
                {
                    "id": phase_id,
                    "name": items[0].phase.name,
                    "objective": items[0].phase.objective,
                    "progress": phase_progress,
                    "total_goals": len(items),
                    "completed_goals": sum(1 for it in items if it.progress >= 100),
                }
            )

        goals = [
            {
                "title": item.goal.title,
                "owner": item.owner.name,
                "owner_email": item.owner.email,
                "progress": item.progress,
                "weight": item.goal.weight,
                "milestone_date": item.goal.milestone_date,
                "deadline": item.goal.deadline,
                "phase_name": item.phase.name,
            }
            for item in snapshots
        ]

        return {
            "id": project.id,
            "name": project.name,
            "deadline": project.deadline,
            "overall_progress": overall_progress,
            "total_goals": len(snapshots),
            "completed_goals": sum(1 for item in snapshots if item.progress >= 100),
            "phases": phases,
            "goals": goals,
        }
