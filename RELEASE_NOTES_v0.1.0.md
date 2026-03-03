# Release Notes - v0.1.0

发布日期：2026-03-03

## 版本概览
v0.1.0 为首个可用版本，交付了项目排程、里程碑提醒、进度采集、报表生成，以及带权限控制的 Web 管理界面。

## 主要功能

- CLI 项目管理
  - 项目创建、阶段添加、目标添加
  - 每日进度录入（支持进度回退备注校验）

- 里程碑与催报
  - 里程碑临近提醒（默认提前 3 天）
  - 里程碑逾期每日持续提醒
  - 缺失进度催报

- 报表能力
  - 日报、周报、月报生成
  - Markdown 落盘 + SMTP 邮件发送
  - 邮件失败重试（指数退避，最多 3 次）

- Web 管理界面
  - 管理员与负责人登录权限
  - 管理员可创建账号并绑定参与者
  - 负责人仅可更新自己负责目标
  - 实时看板（自动刷新）
  - 甘特图视图
  - 夜间模式（黑灰底色）

## 运行与配置

- 默认技术栈：Python + SQLite + Typer + FastAPI + SMTP
- 关键配置：
  - `smtp_host/smtp_port/smtp_user/smtp_pass/mail_from`
  - `near_milestone_days`
  - `auth_secret/auth_token_ttl_minutes`
- 定时任务：支持 `scripts/install_cron.sh` 一键安装受管 cron。

## 质量状态

- 自动化测试通过：`15 passed`
- 主分支提交：`a0b9363`

## 已知限制

- 当前仅单团队单租户，不含组织级权限体系。
- 暂无 IM 通知（飞书/Slack/企业微信）与 SSO。
