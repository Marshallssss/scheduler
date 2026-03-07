from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import typer

from scheduler.config import DEFAULT_CONFIG_PATH, config_template, load_settings
from scheduler.constants import (
    GOAL_TYPE_ISSUE,
    GOAL_TYPE_REQUIREMENT,
    GOAL_TYPE_TASK,
    REPORT_DAILY,
    REPORT_MONTHLY,
    REPORT_WEEKLY,
)
from scheduler.db import create_session_factory, init_db, session_scope
from scheduler.logging_utils import configure_logging
from scheduler.repositories import Repository
from scheduler.services.email_service import EmailService
from scheduler.services.progress_service import ProgressService
from scheduler.services.project_service import ProjectService
from scheduler.services.reminder_service import ReminderService
from scheduler.services.report_service import ReportService
from scheduler.utils import is_last_day_of_month, parse_iso_date

app = typer.Typer(help="项目排程与里程碑追踪 CLI", no_args_is_help=True)
project_app = typer.Typer(help="项目管理")
phase_app = typer.Typer(help="阶段管理")
goal_app = typer.Typer(help="目标管理")
progress_app = typer.Typer(help="进度管理")
reminders_app = typer.Typer(help="提醒任务")
report_app = typer.Typer(help="报表任务")
jobs_app = typer.Typer(help="调度任务")

app.add_typer(project_app, name="project")
app.add_typer(phase_app, name="phase")
app.add_typer(goal_app, name="goal")
app.add_typer(progress_app, name="progress")
app.add_typer(reminders_app, name="reminders")
app.add_typer(report_app, name="report")
app.add_typer(jobs_app, name="jobs")


@app.callback()
def main(
    ctx: typer.Context,
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="配置文件路径"),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


def _load_runtime(ctx: typer.Context):
    config_path: Path = ctx.obj["config_path"]
    settings = load_settings(config_path)
    configure_logging(settings)
    session_factory = create_session_factory(settings)
    return settings, session_factory


def _build_services(repo: Repository, settings):
    email_service = EmailService(settings)
    progress_service = ProgressService(repo)
    reminder_service = ReminderService(repo, email_service=email_service, near_days=settings.near_milestone_days)
    report_service = ReportService(
        repo,
        email_service=email_service,
        report_output_dir=settings.expanded_report_output_dir,
    )
    return progress_service, reminder_service, report_service


def _parse_date_or_exit(raw: str, label: str) -> date:
    try:
        return parse_iso_date(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"{label} 格式错误，应为 YYYY-MM-DD: {raw}") from exc


@app.command("init")
def init_command(ctx: typer.Context) -> None:
    """初始化配置与数据库。"""
    config_path: Path = ctx.obj["config_path"]
    if not config_path.exists():
        config_path.write_text(config_template(), encoding="utf-8")
        typer.echo(f"已生成配置文件: {config_path}")
    else:
        typer.echo(f"配置文件已存在: {config_path}")

    settings = load_settings(config_path)
    settings.expanded_report_output_dir.mkdir(parents=True, exist_ok=True)
    settings.expanded_log_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings)
    typer.echo("数据库初始化完成")


@project_app.command("create")
def project_create(ctx: typer.Context) -> None:
    """交互式创建项目。"""
    settings, session_factory = _load_runtime(ctx)

    name = typer.prompt("项目名称")
    deadline = _parse_date_or_exit(typer.prompt("项目截止日期 (YYYY-MM-DD)"), "项目截止日期")

    participants: list[tuple[str, str]] = []
    typer.echo("开始录入参与者，至少 1 人。姓名留空可结束。")
    while True:
        participant_name = typer.prompt("参与者姓名", default="").strip()
        if not participant_name:
            if participants:
                break
            typer.echo("至少录入 1 位参与者")
            continue
        email = typer.prompt("参与者邮箱").strip()
        participants.append((participant_name, email))

    with session_scope(session_factory) as session:
        repo = Repository(session)
        project_service = ProjectService(repo)
        project = project_service.create_project(name=name, deadline=deadline, participants=participants)
        typer.echo(f"项目创建成功: id={project.id}, name={project.name}")


@project_app.command("list")
def project_list(ctx: typer.Context) -> None:
    """列出项目。"""
    _, session_factory = _load_runtime(ctx)
    with session_scope(session_factory) as session:
        repo = Repository(session)
        projects = repo.list_projects()
        if not projects:
            typer.echo("暂无项目")
            return
        for item in projects:
            typer.echo(f"{item.id}\t{item.name}\tdeadline={item.deadline}\tstatus={item.status}")


@phase_app.command("add")
def phase_add(
    ctx: typer.Context,
    project_id: int = typer.Option(..., "--project-id", help="项目 ID"),
    name: Optional[str] = typer.Option(None, "--name", help="阶段名称"),
    objective: Optional[str] = typer.Option(None, "--objective", help="阶段目标"),
    order: Optional[int] = typer.Option(None, "--order", help="阶段顺序（可选）"),
) -> None:
    """添加阶段目标。"""
    _, session_factory = _load_runtime(ctx)

    use_name = name or typer.prompt("阶段名称")
    use_objective = objective or typer.prompt("阶段目标描述")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        project_service = ProjectService(repo)
        phase = project_service.add_phase(
            project_id=project_id,
            name=use_name,
            objective=use_objective,
            order_index=order,
        )
        typer.echo(f"阶段添加成功: id={phase.id}, order={phase.order_index}")


@goal_app.command("add")
def goal_add(
    ctx: typer.Context,
    phase_id: int = typer.Option(..., "--phase-id", help="阶段 ID"),
    title: Optional[str] = typer.Option(None, "--title", help="目标标题"),
    owner_id: Optional[int] = typer.Option(None, "--owner-id", help="负责人 participant ID"),
    milestone: Optional[str] = typer.Option(None, "--milestone", help="里程碑日期 YYYY-MM-DD"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="目标截止日期 YYYY-MM-DD"),
    goal_type: Optional[str] = typer.Option(None, "--goal-type", help="目标类型 requirement|issue|task"),
    requirement_priority: Optional[int] = typer.Option(None, "--requirement-priority", help="需求优先级 1-5"),
    issue_module: Optional[str] = typer.Option(None, "--issue-module", help="问题单所属模块"),
    issue_total_di: Optional[float] = typer.Option(None, "--issue-total-di", help="问题单总 DI"),
    issue_target_di: Optional[float] = typer.Option(None, "--issue-target-di", help="问题单目标 DI"),
    note: Optional[str] = typer.Option(None, "--note", help="目标备注（task 类型必填）"),
    weight: Optional[float] = typer.Option(None, "--weight", help="权重，默认 1.0"),
) -> None:
    """添加小目标。"""
    _, session_factory = _load_runtime(ctx)

    with session_scope(session_factory) as session:
        repo = Repository(session)
        project_service = ProjectService(repo)

        phase = repo.get_phase(phase_id)
        if phase is None:
            raise typer.BadParameter(f"阶段不存在: {phase_id}")
        participants = repo.list_project_participants(phase.project_id)
        if not participants:
            raise typer.BadParameter("该项目尚无参与者，无法设置负责人")

        if owner_id is None:
            typer.echo("可选负责人：")
            for item in participants:
                typer.echo(f"- {item.id}: {item.name} <{item.email}>")
            owner_id = int(typer.prompt("负责人 ID"))

        use_title = title or typer.prompt("目标标题")
        milestone_date = _parse_date_or_exit(milestone or typer.prompt("里程碑日期 (YYYY-MM-DD)"), "里程碑日期")
        deadline_date = _parse_date_or_exit(deadline or typer.prompt("目标截止日期 (YYYY-MM-DD)"), "目标截止日期")
        use_goal_type = (
            goal_type or typer.prompt("目标类型 requirement|issue|task", default=GOAL_TYPE_REQUIREMENT)
        ).strip().lower()

        use_requirement_priority = requirement_priority
        use_issue_module = issue_module
        use_issue_total_di = issue_total_di
        use_issue_target_di = issue_target_di
        use_note = note
        if use_goal_type == GOAL_TYPE_REQUIREMENT:
            if use_requirement_priority is None:
                priority_raw = typer.prompt("需求优先级(1-5，可留空)", default="")
                use_requirement_priority = int(priority_raw) if priority_raw.strip() else None
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None
        elif use_goal_type == GOAL_TYPE_ISSUE:
            if use_issue_module is None:
                use_issue_module = typer.prompt("问题单所属模块")
            if use_issue_total_di is None:
                use_issue_total_di = float(typer.prompt("问题单总 DI"))
            if use_issue_target_di is None:
                use_issue_target_di = float(typer.prompt("问题单目标 DI", default="0"))
        elif use_goal_type == GOAL_TYPE_TASK:
            use_requirement_priority = None
            use_issue_module = None
            use_issue_total_di = None
            use_issue_target_di = None
            if use_note is None or not use_note.strip():
                use_note = typer.prompt("事务型目标备注（明确事务内容）").strip()

        goal = project_service.add_goal(
            phase_id=phase_id,
            title=use_title,
            owner_participant_id=owner_id,
            milestone_date=milestone_date,
            deadline=deadline_date,
            weight=weight,
            goal_type=use_goal_type,
            requirement_priority=use_requirement_priority,
            issue_module=use_issue_module,
            issue_total_di=use_issue_total_di,
            issue_target_di=use_issue_target_di,
            note=use_note,
        )
        typer.echo(
            f"目标添加成功: id={goal.id}, title={goal.title}, type={goal.goal_type}, "
            f"weight={goal.weight}"
        )


@progress_app.command("collect")
def progress_collect(
    ctx: typer.Context,
    project_id: int = typer.Option(..., "--project-id", help="项目 ID"),
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="采集日期 YYYY-MM-DD"),
    updated_by: str = typer.Option("project_manager", "--updated-by", help="更新人"),
) -> None:
    """交互式录入每日进度。"""
    _, session_factory = _load_runtime(ctx)
    update_date = _parse_date_or_exit(on_date, "采集日期")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        progress_service = ProgressService(repo)

        snapshots = repo.list_goal_snapshots_by_project(project_id=project_id, as_of=update_date)
        if not snapshots:
            typer.echo("该项目暂无目标")
            return

        typer.echo(f"开始录入 {len(snapshots)} 个目标在 {update_date} 的进度")
        for snapshot in snapshots:
            note = None
            if snapshot.goal.goal_type == GOAL_TYPE_ISSUE:
                default_remaining = snapshot.remaining_di
                if default_remaining is None:
                    default_remaining = snapshot.goal.issue_total_di if snapshot.goal.issue_total_di is not None else 0.0
                target_di = snapshot.goal.issue_target_di if snapshot.goal.issue_target_di is not None else 0.0
                di_gap = default_remaining - target_di
                prompt = (
                    f"[{snapshot.goal.id}] {snapshot.goal.title} "
                    f"(当前 {snapshot.progress:.2f}%, 剩余DI {default_remaining:.2f}, 目标DI {target_di:.2f}, 差值 {di_gap:.2f})"
                )
                raw_remaining = typer.prompt(prompt, default=str(default_remaining))
                try:
                    new_remaining = float(raw_remaining)
                except ValueError as exc:
                    raise typer.BadParameter(f"剩余DI必须为数字: {raw_remaining}") from exc

                if new_remaining > default_remaining:
                    note = typer.prompt("检测到剩余DI增加，请填写备注")

                progress_service.record_progress(
                    goal_id=snapshot.goal.id,
                    update_date=update_date,
                    progress_percent=None,
                    remaining_di=new_remaining,
                    note=note,
                    updated_by=updated_by,
                )
            else:
                prompt = f"[{snapshot.goal.id}] {snapshot.goal.title} (当前 {snapshot.progress:.2f}%)"
                raw_progress = typer.prompt(prompt, default=str(snapshot.progress))
                try:
                    new_progress = float(raw_progress)
                except ValueError as exc:
                    raise typer.BadParameter(f"完成率必须为数字: {raw_progress}") from exc

                if new_progress < snapshot.progress:
                    note = typer.prompt("检测到进度回退，请填写备注")

                progress_service.record_progress(
                    goal_id=snapshot.goal.id,
                    update_date=update_date,
                    progress_percent=new_progress,
                    note=note,
                    updated_by=updated_by,
                )

        summary = progress_service.build_project_progress(project_id=project_id, as_of=update_date)
        typer.echo(
            f"录入完成: 项目 {summary.project_name} 总完成率 {summary.progress_percent:.2f}% "
            f"({summary.completed_goals}/{summary.total_goals})"
        )


@reminders_app.command("run")
def reminders_run(
    ctx: typer.Context,
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
) -> None:
    """执行临近/逾期里程碑提醒。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, reminder_service, _ = _build_services(repo, settings)
        result = reminder_service.run_milestone_reminders(on_date=run_date)
        typer.echo(f"提醒执行完成: sent={result.sent}, failed={result.failed}, skipped={result.skipped}")


@reminders_app.command("nudge-missing")
def reminders_nudge_missing(
    ctx: typer.Context,
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
) -> None:
    """执行缺失进度催报。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, reminder_service, _ = _build_services(repo, settings)
        result = reminder_service.run_missing_progress_nudges(on_date=run_date)
        typer.echo(f"催报执行完成: sent={result.sent}, failed={result.failed}, skipped={result.skipped}")


@report_app.command("generate")
def report_generate(
    ctx: typer.Context,
    period: str = typer.Option(..., "--period", help="daily|weekly|monthly"),
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
) -> None:
    """生成并发送报表。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, _, report_service = _build_services(repo, settings)
        result = report_service.generate_report(period=period, run_date=run_date)
        typer.echo(f"报表生成完成: path={result.markdown_path}, status={result.status}, report_id={result.report_id}")


@jobs_app.command("run-daily")
def jobs_run_daily(
    ctx: typer.Context,
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
    step: str = typer.Option("all", "--step", help="all|reminders|progress-nudge|report"),
) -> None:
    """执行每日任务。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    if step not in {"all", "reminders", "progress-nudge", "report"}:
        raise typer.BadParameter("step 必须为 all|reminders|progress-nudge|report")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, reminder_service, report_service = _build_services(repo, settings)

        if step in {"all", "reminders"}:
            reminder_result = reminder_service.run_milestone_reminders(run_date)
            typer.echo(
                f"[daily] milestone reminders: sent={reminder_result.sent}, "
                f"failed={reminder_result.failed}, skipped={reminder_result.skipped}"
            )
        if step in {"all", "progress-nudge"}:
            nudge_result = reminder_service.run_missing_progress_nudges(run_date)
            typer.echo(
                f"[daily] progress nudge: sent={nudge_result.sent}, "
                f"failed={nudge_result.failed}, skipped={nudge_result.skipped}"
            )
        if step in {"all", "report"}:
            report_result = report_service.generate_report(period=REPORT_DAILY, run_date=run_date)
            typer.echo(f"[daily] report: path={report_result.markdown_path}, status={report_result.status}")


@jobs_app.command("run-weekly")
def jobs_run_weekly(
    ctx: typer.Context,
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
) -> None:
    """执行周报任务。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, _, report_service = _build_services(repo, settings)
        result = report_service.generate_report(period=REPORT_WEEKLY, run_date=run_date)
        typer.echo(f"[weekly] report: path={result.markdown_path}, status={result.status}")


@jobs_app.command("run-monthly")
def jobs_run_monthly(
    ctx: typer.Context,
    on_date: str = typer.Option(date.today().isoformat(), "--date", help="执行日期 YYYY-MM-DD"),
) -> None:
    """执行月报任务；仅在月末当天生成。"""
    settings, session_factory = _load_runtime(ctx)
    run_date = _parse_date_or_exit(on_date, "执行日期")

    if not is_last_day_of_month(run_date):
        typer.echo(f"{run_date} 不是月末，跳过月报生成")
        return

    with session_scope(session_factory) as session:
        repo = Repository(session)
        _, _, report_service = _build_services(repo, settings)
        result = report_service.generate_report(period=REPORT_MONTHLY, run_date=run_date)
        typer.echo(f"[monthly] report: path={result.markdown_path}, status={result.status}")


@app.command("web")
def web_run(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host", help="监听地址"),
    port: int = typer.Option(8787, "--port", help="监听端口"),
) -> None:
    """启动 Web 管理界面。"""
    settings, _ = _load_runtime(ctx)
    from scheduler.web_app import create_app
    import uvicorn

    web_app = create_app(settings)
    typer.echo(f"Web 已启动: http://{host}:{port}")
    uvicorn.run(web_app, host=host, port=port)


if __name__ == "__main__":
    app()
