from __future__ import annotations

from pathlib import Path

import pytest

from scheduler.config import Settings
from scheduler.db import create_session_factory, init_db, session_scope


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'scheduler.db'}",
        report_output_dir=str(tmp_path / "reports"),
        log_dir=str(tmp_path / "logs"),
        smtp_host="",
        mail_from="",
    )


@pytest.fixture()
def session_factory(settings):
    init_db(settings)
    return create_session_factory(settings)


@pytest.fixture()
def session(session_factory):
    with session_scope(session_factory) as db_session:
        yield db_session
