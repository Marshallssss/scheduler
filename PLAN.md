# 项目排程与里程碑追踪 CLI 系统（Python + SQLite + Cron + Email）

## 摘要
- 交付一个单团队内部使用的命令行软件，支持项目建档、分阶段目标拆解、每个小目标单一负责人、里程碑管理、每日进度采集、临近/逾期提醒、日报/周报/月报生成与邮件发送。
- 运行形态：`Python CLI` + `SQLite` + `系统 Cron` + `SMTP 邮件`。
- 你已确认的关键规则：交互式录入、进度 0-100、里程碑提前 3 天提醒、仅通知负责人、按小目标权重聚合、提醒 09:00、日报 17:55、周报周五 18:00、月报月末 18:10。

## 范围定义
- In scope：项目生命周期管理、里程碑日检、进度采集与聚合、报告生成、邮件通知、可追溯日志。
- Out of scope：Web UI、多租户、复杂权限系统、IM（飞书/企微/Slack）集成、自动解析邮件回复填报。

## 实施清单（3-6 步）
1. 初始化 Python 工程与 CLI 骨架，落地配置加载、日志、数据库连接与迁移。
2. 实现核心数据模型与仓储层（项目/阶段/目标/里程碑/进度更新/提醒日志/报表记录）。
3. 实现交互式命令：建项目、加参与者、加阶段目标、录入每日进度、手动触发报表与提醒。
4. 实现定时任务入口：每日检查提醒、日报/周报/月报生成、邮件发送与失败重试。
5. 补齐自动化测试与验收脚本，提供 cron 配置模板和部署说明。

## 代码与目录规划（新建）
- `pyproject.toml`：依赖与入口脚本定义。
- `scheduler/cli.py`：Typer 命令入口。
- `scheduler/config.py`：配置模型与 `.scheduler.toml`/环境变量读取。
- `scheduler/db.py`：SQLAlchemy 引擎、会话、迁移入口。
- `scheduler/models.py`：ORM 模型。
- `scheduler/repositories.py`：数据库访问封装。
- `scheduler/services/project_service.py`：项目/阶段/目标管理。
- `scheduler/services/progress_service.py`：每日进度采集与聚合。
- `scheduler/services/reminder_service.py`：临近/逾期提醒判断与去重。
- `scheduler/services/report_service.py`：日报/周报/月报生成。
- `scheduler/services/email_service.py`：SMTP 发送与失败重试。
- `scheduler/templates/*.md.j2`：报表与邮件模板。
- `tests/*`：单元测试与集成测试。
- `README.md`：安装、使用、cron 配置。

## 重要公共接口 / 类型变更
### CLI 命令接口（稳定对外）
1. `scheduler init`：初始化数据库与默认配置模板。
2. `scheduler project create`：交互式创建项目（名称、截止日期、参与者）。
3. `scheduler phase add`：添加阶段目标。
4. `scheduler goal add`：添加小目标（负责人、权重、里程碑、截止日期）。
5. `scheduler progress collect --project-id <id> --date <YYYY-MM-DD>`：交互式逐项录入完成率。
6. `scheduler reminders run --date <YYYY-MM-DD>`：执行临近/逾期提醒。
7. `scheduler report generate --period daily|weekly|monthly --date <YYYY-MM-DD>`：生成报表并发送邮件。
8. `scheduler jobs run-daily`：串行执行“提醒 + 催报 + 日报”。
9. `scheduler jobs run-weekly`：生成并发送周报。
10. `scheduler jobs run-monthly`：生成并发送月报。

### 配置接口（`.scheduler.toml`）
- `timezone = "Asia/Shanghai"`
- `database_url = "sqlite:///~/.project_scheduler/scheduler.db"`
- `smtp_host/smtp_port/smtp_user/smtp_pass`
- `mail_from`
- `daily_reminder_time = "09:00"`
- `daily_report_time = "17:55"`
- `weekly_report_time = "FRI 18:00"`
- `monthly_report_time = "LAST_DAY 18:10"`
- `near_milestone_days = 3`
- `report_output_dir = "~/.project_scheduler/reports"`

### 核心数据类型（逻辑）
- `Project`：`id, name, deadline, status, created_at`
- `Participant`：`id, project_id, name, email`
- `Phase`：`id, project_id, name, objective, order_index`
- `Goal`：`id, phase_id, title, owner_participant_id, weight, milestone_date, deadline, status`
- `GoalProgressUpdate`：`id, goal_id, date, progress_percent, note, updated_by`
- `ReminderLog`：`id, goal_id, date, reminder_type(near|overdue|missing_update), recipient, sent_at, status`
- `ReportRecord`：`id, period(daily|weekly|monthly), period_start, period_end, markdown_path, emailed_at, status`

## 关键业务规则（实现级）
- 临近里程碑：`0 < milestone_date - today <= 3` 且目标未完成（进度 < 100）时提醒负责人。
- 逾期里程碑：`milestone_date < today` 且目标未完成，每日持续提醒直到完成。
- 进度采集：项目经理每天执行 `progress collect`，按目标录入 0-100；允许回退但需备注原因。
- 项目整体完成率：`sum(goal_progress * weight) / sum(weight)`，权重缺省为等权（1.0）。
- 阶段完成率：同上，仅聚合该阶段内目标。
- 日报周期：当日 00:00-17:55；周报周期：自然周（周一至周日）但发送在周五 18:00；月报周期：自然月。
- 去重：同一目标同一天同类提醒只发一次（依赖 `ReminderLog`）。

## 定时执行与运维
- Cron 任务（示例）：
1. `0 9 * * * scheduler jobs run-daily --step reminders`
2. `45 17 * * * scheduler jobs run-daily --step progress-nudge`
3. `55 17 * * * scheduler report generate --period daily`
4. `0 18 * * 5 scheduler jobs run-weekly`
5. `10 18 28-31 * * scheduler jobs run-monthly`（命令内判断“是否月末”）
- 日志：结构化日志写入 `~/.project_scheduler/logs/app.log`，保留最近 30 天。
- 邮件失败重试：指数退避最多 3 次；最终失败写入日志并标记 `ReportRecord.status=failed`。

## 测试用例与验收场景
1. 里程碑提醒边界：第 4/3/1/0/-1 天的触发正确性。
2. 逾期持续提醒：连续 3 天未完成时每天都发；完成后停止。
3. 权重聚合：等权、非等权、缺省权重混合场景计算正确。
4. 进度采集：非法值（<0, >100, 非数字）拦截；回退需备注。
5. 去重：同日重复执行提醒命令不重复发送同类邮件。
6. 报表周期：跨周、跨月边界统计正确。
7. 邮件失败链路：SMTP 失败触发重试与失败落库。
8. 集成验收：创建项目 -> 每日录入 -> 自动提醒 -> 生成三类报表全链路通过。

## 交付标准
- `scheduler` CLI 在干净环境可安装运行。
- 按给定 cron 配置可自动触发提醒与报表发送。
- 日报/周报/月报均落地 Markdown 并成功邮件发送。
- 核心规则测试通过，覆盖率目标 >= 80%（服务层）。

## 默认假设与已选项
- 默认时区 `Asia/Shanghai`。
- 通知对象为每个小目标负责人（非全员群发）。
- 进度由项目经理统一录入（非自动采集、非邮件解析）。
- 报表默认语言为中文。
- 当前版本为单团队单租户，不做权限分层与 SSO。
