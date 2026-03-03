from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from scheduler.config import Settings
from scheduler.models import Base


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return
    raw = database_url.replace("sqlite:///", "", 1)
    db_path = Path(raw)
    db_path.parent.mkdir(parents=True, exist_ok=True)


def create_engine_from_settings(settings: Settings) -> Engine:
    database_url = settings.expanded_database_url
    _ensure_sqlite_parent_dir(database_url)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine_from_settings(settings)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _ensure_sqlite_columns(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        goal_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(goals)").fetchall()}
        progress_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(goal_progress_updates)").fetchall()}

        if "goal_type" not in goal_columns:
            conn.exec_driver_sql("ALTER TABLE goals ADD COLUMN goal_type TEXT NOT NULL DEFAULT 'requirement'")
        if "requirement_priority" not in goal_columns:
            conn.exec_driver_sql("ALTER TABLE goals ADD COLUMN requirement_priority INTEGER")
        if "issue_module" not in goal_columns:
            conn.exec_driver_sql("ALTER TABLE goals ADD COLUMN issue_module TEXT")
        if "issue_total_di" not in goal_columns:
            conn.exec_driver_sql("ALTER TABLE goals ADD COLUMN issue_total_di FLOAT")
        if "note" not in goal_columns:
            conn.exec_driver_sql("ALTER TABLE goals ADD COLUMN note TEXT")

        if "remaining_di" not in progress_columns:
            conn.exec_driver_sql("ALTER TABLE goal_progress_updates ADD COLUMN remaining_di FLOAT")
        if "requirement_total_count" not in progress_columns:
            conn.exec_driver_sql("ALTER TABLE goal_progress_updates ADD COLUMN requirement_total_count INTEGER")
        if "requirement_done_count" not in progress_columns:
            conn.exec_driver_sql("ALTER TABLE goal_progress_updates ADD COLUMN requirement_done_count INTEGER")


def init_db(settings: Settings) -> None:
    engine = create_engine_from_settings(settings)
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
