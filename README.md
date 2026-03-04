# 项目排程与里程碑追踪 CLI

基于 Python + SQLite + Cron + SMTP 的单团队项目管理工具，支持：

- 项目/阶段/目标建档
- 每个小目标单负责人
- 每日进度采集（0-100）
- 里程碑临近/逾期提醒
- 日报/周报/月报生成（Markdown + 邮件）

## 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## 2. 初始化

```bash
scheduler init
```

首次执行会生成 `.scheduler.toml`，请填写 SMTP 配置：

```toml
timezone = "Asia/Shanghai"
database_url = "sqlite:///~/.project_scheduler/scheduler.db"

smtp_host = "smtp.example.com"
smtp_port = 587
smtp_user = "user@example.com"
smtp_pass = "replace-me"
mail_from = "pm-bot@example.com"

daily_reminder_time = "09:00"
daily_report_time = "17:55"
weekly_report_time = "FRI 18:00"
monthly_report_time = "LAST_DAY 18:10"
near_milestone_days = 3

report_output_dir = "~/.project_scheduler/reports"
log_dir = "~/.project_scheduler/logs"

auth_secret = "change-me-please"
auth_token_ttl_minutes = 720
```

也可以通过环境变量覆盖：

- `SCHEDULER_DATABASE_URL`
- `SCHEDULER_SMTP_HOST`
- `SCHEDULER_SMTP_PORT`
- `SCHEDULER_SMTP_USER`
- `SCHEDULER_SMTP_PASS`
- `SCHEDULER_MAIL_FROM`
- `SCHEDULER_NEAR_MILESTONE_DAYS`
- `SCHEDULER_AUTH_SECRET`
- `SCHEDULER_AUTH_TOKEN_TTL_MINUTES`

## 3. 常用命令

```bash
# 交互式创建项目
scheduler project create

# 添加阶段
scheduler phase add --project-id 1 --name "需求" --objective "完成需求冻结"

# 添加目标
scheduler goal add --phase-id 1 --title "完成接口定义" --owner-id 1 --milestone 2026-03-10 --deadline 2026-03-15 --weight 2

# 每日采集进度
scheduler progress collect --project-id 1 --date 2026-03-02

# 里程碑提醒
scheduler reminders run --date 2026-03-02

# 缺失进度催报
scheduler reminders nudge-missing --date 2026-03-02

# 生成日报/周报/月报
scheduler report generate --period daily --date 2026-03-02
scheduler report generate --period weekly --date 2026-03-06
scheduler report generate --period monthly --date 2026-03-31
```

## 4. Web 前端界面

启动 Web 界面（默认 `127.0.0.1:8787`）：

```bash
scheduler --config .scheduler.toml web --host 0.0.0.0 --port 8787
```

浏览器打开：

- `http://127.0.0.1:8787`（本机访问）
- `http://<你的机器IP>:8787`（局域网访问）

Web 页面支持：

- 账号认证：初始化管理员、登录、登出
- 权限控制：`admin`（项目配置与账号管理）/ `owner`（仅更新自己负责目标）
- 项目创建（项目名、参与者、截止日期）
- 阶段与目标管理（新增/修改/删除，目标负责人、权重、里程碑、截止日期）
- 目标备注（悬停可查看详细标注）
- 每日进度更新：
  - 需求型：按“需求总数 + 已完成需求数”自动计算
  - 问题单型：按“剩余 DI”跟踪
  - 回退（或剩余 DI 增加）需备注
- 项目看板实时刷新（每 15 秒轮询）
- 甘特图时间轴（按里程碑~截止日期显示目标区间与完成率）
- 界面页签：管理员入口独立页签，创建/维护页签位于甘特图下方
- 进度预警着色：
  - 截止前 3 天未达 80%：黄色
  - 截止前 1 天未达 90%：红色
  - 其他场景：绿色

首次进入 Web 时：

1. 若系统无账号，先创建第一个管理员（bootstrap）。
2. 管理员登录后，可在“账号管理”中创建负责人账号，并绑定到具体项目参与者。
3. 负责人登录后，只能看到自己参与项目，并且仅能更新自己负责的目标进度。

## 5. 生产版 Cron（一键安装）

先确认配置文件已经就绪（例如 `./.scheduler.toml`），再执行：

```bash
scripts/install_cron.sh --config "$(pwd)/.scheduler.toml"
```

预览将要写入的 crontab（不落库）：

```bash
scripts/install_cron.sh --config "$(pwd)/.scheduler.toml" --dry-run
```

卸载受管任务（不影响你已有其他 cron）：

```bash
scripts/uninstall_cron.sh
```

脚本默认安装以下调度规则（`CRON_TZ=Asia/Shanghai`）：

```cron
0 9 * * * scheduler jobs run-daily --step reminders
45 17 * * * scheduler jobs run-daily --step progress-nudge
55 17 * * * scheduler report generate --period daily
0 18 * * 5 scheduler jobs run-weekly
10 18 28-31 * * scheduler jobs run-monthly
```

月报命令会在非月末自动跳过；脚本每次安装/卸载都会自动备份当前 crontab 到 `~/.project_scheduler/cron_backups/`。

验证安装结果：

```bash
crontab -l
```

## 6. Windows 一键部署（双击）

在 Windows 上可直接双击：

`scripts\deploy_windows.bat`

若网络不稳定，建议先双击：

`scripts\build_windows_wheels.bat`

该脚本会把依赖预下载到项目根目录 `_wheels`，`deploy/upgrade` 会优先使用本地依赖包安装。
仓库也可直接提交 `_wheels` 目录用于离线部署；依赖版本更新时再重新执行该脚本刷新。

脚本会自动完成：

1. 创建 `.venv`
2. 安装项目依赖
3. 初始化 `.scheduler.toml` 与数据库（若不存在）
4. 启动 Web（`http://127.0.0.1:8787`）

说明：

- Windows 不使用 `cron`，建议使用“任务计划程序”配置定时任务。
- 首次部署后请编辑 `.scheduler.toml` 填写 SMTP 等配置。
- 若部署失败，请查看日志：`%USERPROFILE%\.project_scheduler\logs\windows_deploy.log`
- 为减少耗时，脚本默认仅在新建 `.venv` 时升级 `pip/setuptools/wheel`；如需强制升级可先执行：`set SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1`
- 如需彻底禁用在线源并强制只使用 `_wheels`：先执行 `set SCHEDULER_OFFLINE_ONLY=1`，再运行脚本。

### Windows 后续日常启动（双击）

首次部署成功后，日常启动建议双击：

`scripts\start_windows.bat`

该脚本仅负责启动 Web，不会重复安装依赖。  
若启动失败，请查看日志：`%USERPROFILE%\.project_scheduler\logs\windows_start.log`

## 7. 一键升级（迭代场景）

频繁迭代时，推荐使用升级脚本，不需要手工执行 `git pull` + `pip install`。

### Linux / macOS

```bash
scripts/upgrade.sh
```

脚本会自动执行：

1. 检查工作区是否干净（有未提交改动会终止，避免覆盖）
2. 拉取当前分支最新代码（`git pull --ff-only`）
3. 安装/更新依赖（`pip install -e .`）
4. 执行 `scheduler init` 触发数据库结构补齐（安全幂等）

### Windows（双击，离线整包升级）

可直接双击：

`scripts\upgrade_windows.bat`

脚本默认执行离线整包升级，不依赖 Git。  
自动检测顺序：

1. `%PROJECT_DIR%\_upgrade\*.zip`（推荐）
2. `%USERPROFILE%\Downloads\*scheduler*.zip`
3. 若都未命中，提示手工输入 zip 路径或解压目录

推荐流程（最省事）：

1. 保持当前项目目录不变（即你旧版本正在运行的目录）。
2. （推荐）先双击 `scripts\build_windows_wheels.bat`，把依赖预下载到 `_wheels`。
3. 在项目根目录创建 `_upgrade` 文件夹（若不存在）。
4. 下载最新源码压缩包（zip）到 `%PROJECT_DIR%\_upgrade\`。
5. 双击 `scripts\upgrade_windows.bat`。
6. 脚本会自动解压、替换代码、升级依赖并执行 `init`。

也可命令行显式指定升级包/目录：

```bat
scripts\upgrade_windows.bat "D:\Downloads\scheduler-v0.2.0.zip"
scripts\upgrade_windows.bat "D:\Downloads\scheduler-v0.2.0"
scripts\upgrade_windows.bat --from-package "D:\Downloads\scheduler-v0.2.0.zip"
scripts\build_windows_wheels.bat
```

升级时会保留本地状态文件/目录（如 `.venv`、`.scheduler.toml`、`.git`），并在 `_wheels` 存在时优先使用离线依赖包。
请务必在“旧安装目录”里双击运行 `scripts\upgrade_windows.bat`；若当前目录同时缺少 `.scheduler.toml` 和 `.venv`，脚本会直接报错，避免升级到了错误目录。
升级包必须是完整源码包（至少包含 `pyproject.toml`、`scheduler/`、`scripts/`）；若缺少 `scripts` 目录或 `scripts\upgrade_windows.bat`，脚本会直接报错终止，避免“显示成功但实际半升级”。
为减少耗时，升级脚本默认会跳过 `pip/setuptools/wheel` 的重复升级；如需强制升级可先执行：`set SCHEDULER_FORCE_PIP_TOOLS_UPGRADE=1`。
如需彻底禁用在线源并强制只使用 `_wheels`：先执行 `set SCHEDULER_OFFLINE_ONLY=1`，再运行脚本。

脚本会在安装前自动检查并修复 `pip._vendor.distlib\t64.exe` 缺失（常见报错：`Unable to find resource t64.exe`），减少因虚拟环境内 pip 资源损坏导致的升级失败。
另外，代码替换后会校验 `scripts/` 目录是否完整同步；若发现缺失文件会报错并提示查看升级日志。

失败日志：

- `%USERPROFILE%\.project_scheduler\logs\windows_upgrade.log`

## 8. 测试

```bash
pytest -q
```

## 9. 日志与产物

- 日志：`~/.project_scheduler/logs/app.log`（保留 30 天）
- 报表：`~/.project_scheduler/reports/*.md`
