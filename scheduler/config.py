from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Optional
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

DEFAULT_CONFIG_PATH = Path(".scheduler.toml")


@dataclass
class Settings:
    timezone: str = "Asia/Shanghai"
    database_url: str = "sqlite:///~/.project_scheduler/scheduler.db"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    mail_from: str = ""
    daily_reminder_time: str = "09:00"
    daily_report_time: str = "17:55"
    weekly_report_time: str = "FRI 18:00"
    monthly_report_time: str = "LAST_DAY 18:10"
    near_milestone_days: int = 3
    report_output_dir: str = "~/.project_scheduler/reports"
    log_dir: str = "~/.project_scheduler/logs"
    auth_secret: str = "change-me-please"
    auth_token_ttl_minutes: int = 720

    @property
    def expanded_report_output_dir(self) -> Path:
        return Path(self.report_output_dir).expanduser().resolve()

    @property
    def expanded_log_dir(self) -> Path:
        return Path(self.log_dir).expanduser().resolve()

    @property
    def expanded_database_url(self) -> str:
        if self.database_url.startswith("sqlite:///"):
            raw = self.database_url.replace("sqlite:///", "", 1)
            expanded = str(Path(raw).expanduser().resolve())
            return f"sqlite:///{expanded}"
        return self.database_url


def _read_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _env_override(values: dict) -> dict:
    mappings = {
        "timezone": "SCHEDULER_TIMEZONE",
        "database_url": "SCHEDULER_DATABASE_URL",
        "smtp_host": "SCHEDULER_SMTP_HOST",
        "smtp_port": "SCHEDULER_SMTP_PORT",
        "smtp_user": "SCHEDULER_SMTP_USER",
        "smtp_pass": "SCHEDULER_SMTP_PASS",
        "mail_from": "SCHEDULER_MAIL_FROM",
        "daily_reminder_time": "SCHEDULER_DAILY_REMINDER_TIME",
        "daily_report_time": "SCHEDULER_DAILY_REPORT_TIME",
        "weekly_report_time": "SCHEDULER_WEEKLY_REPORT_TIME",
        "monthly_report_time": "SCHEDULER_MONTHLY_REPORT_TIME",
        "near_milestone_days": "SCHEDULER_NEAR_MILESTONE_DAYS",
        "report_output_dir": "SCHEDULER_REPORT_OUTPUT_DIR",
        "log_dir": "SCHEDULER_LOG_DIR",
        "auth_secret": "SCHEDULER_AUTH_SECRET",
        "auth_token_ttl_minutes": "SCHEDULER_AUTH_TOKEN_TTL_MINUTES",
    }
    merged = dict(values)
    for key, env in mappings.items():
        value = os.getenv(env)
        if value is None or value == "":
            continue
        merged[key] = value
    return merged


def load_settings(config_path: Optional[Path] = None) -> Settings:
    path = config_path or DEFAULT_CONFIG_PATH
    data = _read_config_file(path)
    merged = _env_override(data)

    if "smtp_port" in merged:
        merged["smtp_port"] = int(merged["smtp_port"])
    if "near_milestone_days" in merged:
        merged["near_milestone_days"] = int(merged["near_milestone_days"])
    if "auth_token_ttl_minutes" in merged:
        merged["auth_token_ttl_minutes"] = int(merged["auth_token_ttl_minutes"])

    return Settings(**merged)


def config_template() -> str:
    return """timezone = \"Asia/Shanghai\"
database_url = \"sqlite:///~/.project_scheduler/scheduler.db\"

smtp_host = \"smtp.example.com\"
smtp_port = 587
smtp_user = \"user@example.com\"
smtp_pass = \"replace-me\"
mail_from = \"pm-bot@example.com\"

daily_reminder_time = \"09:00\"
daily_report_time = \"17:55\"
weekly_report_time = \"FRI 18:00\"
monthly_report_time = \"LAST_DAY 18:10\"
near_milestone_days = 3

report_output_dir = \"~/.project_scheduler/reports\"
log_dir = \"~/.project_scheduler/logs\"

auth_secret = \"change-me-please\"
auth_token_ttl_minutes = 720
"""
