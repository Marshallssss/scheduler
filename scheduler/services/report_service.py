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


@dataclass
class RenderedReport:
    period: str
    run_date: date
    start_date: date
    end_date: date
    subject: str
    markdown: str


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
        return self.dispatch_report(period=period, run_date=run_date)

    def render_report(self, period: str, run_date: date) -> RenderedReport:
        if period not in REPORT_PERIODS:
            raise ValueError(f"不支持的报表周期: {period}")

        start_date, end_date = self.period_window(period, run_date)
        content = self._render_markdown(period=period, start_date=start_date, end_date=end_date, as_of=end_date)
        subject = self._subject(period, start_date, end_date)
        return RenderedReport(
            period=period,
            run_date=run_date,
            start_date=start_date,
            end_date=end_date,
            subject=subject,
            markdown=content,
        )

    def dispatch_report(
        self,
        period: str,
        run_date: date,
        recipients: list[str] | None = None,
        markdown: str | None = None,
    ) -> ReportResult:
        rendered = self.render_report(period=period, run_date=run_date)
        content = rendered.markdown if markdown is None else markdown

        self.report_output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = self.report_output_dir / f"{period}_{rendered.start_date}_{rendered.end_date}_{timestamp}.md"
        file_path.write_text(content, encoding="utf-8")

        record = self.repo.create_report_record(
            period=period,
            period_start=rendered.start_date,
            period_end=rendered.end_date,
            markdown_path=str(file_path),
            status="generated",
        )

        use_recipients = recipients
        if use_recipients is None:
            use_recipients = sorted({participant.email for participant in self.repo.list_all_participants()})
        sent = self.email_service.send_email(use_recipients, rendered.subject, content)
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
        goal_details = [
            goal
            for project in projects_context
            for goal in project["goals"]
        ]

        updates = self.repo.list_progress_updates_between(start_date, end_date)
        rollback_count = sum(1 for update in updates if (update.note or "").strip())

        return template.render(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            period=period,
            start_date=start_date,
            end_date=end_date,
            projects=projects_context,
            goal_details=goal_details,
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
                "project_id": project.id,
                "project_name": self._markdown_cell(project.name),
                "title": self._markdown_cell(item.goal.title),
                "owner": self._markdown_cell(item.owner.name),
                "owner_email": item.owner.email,
                "progress": item.progress,
                "progress_display": self._progress_display(item.progress, item.progress_state),
                "weight": item.goal.weight,
                "milestone_date": item.goal.milestone_date,
                "deadline": item.goal.deadline,
                "phase_name": self._markdown_cell(item.phase.name),
                "progress_state": item.progress_state,
                "progress_state_label": self._markdown_cell(self._progress_state_label(item.progress_state)),
                "risk_item": self._markdown_cell(self._risk_item(item.progress_state, item.risk_note)),
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

    def _progress_state_label(self, progress_state: str) -> str:
        if progress_state == "ahead":
            return "提前"
        if progress_state == "delayed":
            return "delay"
        return "正常"

    def _progress_display(self, progress: float, progress_state: str) -> str:
        value = f"{progress:.2f}%"
        if progress_state == "delayed":
            return f"**{value}**"
        return value

    def _risk_item(self, progress_state: str, risk_note: str | None) -> str:
        clean_note = risk_note.strip() if risk_note else ""
        parts: list[str] = []
        if progress_state == "delayed":
            parts.append("进度delay")
        if clean_note:
            parts.append(clean_note)
        return "；".join(parts) if parts else "-"

    def _markdown_cell(self, value: object) -> str:
        text = str(value).strip() if value is not None else "-"
        if not text:
            return "-"
        return text.replace("|", r"\|").replace("\r\n", "\n").replace("\n", "<br>")
