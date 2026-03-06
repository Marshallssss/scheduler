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
        if "progress_state" not in progress_columns:
            conn.exec_driver_sql("ALTER TABLE goal_progress_updates ADD COLUMN progress_state TEXT DEFAULT 'normal'")
        if "risk_note" not in progress_columns:
            conn.exec_driver_sql("ALTER TABLE goal_progress_updates ADD COLUMN risk_note TEXT")
        conn.exec_driver_sql(
            "UPDATE goal_progress_updates SET progress_state='normal' "
            "WHERE progress_state IS NULL OR TRIM(progress_state) = ''"
        )

        goals_table_sql = conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='goals'"
        ).scalar()
        if goals_table_sql and "'task'" not in str(goals_table_sql).lower():
            _rebuild_sqlite_goals_table_with_task_constraint(conn)


def _rebuild_sqlite_goals_table_with_task_constraint(conn) -> None:
    # Rebuild goals table so legacy SQLite databases can accept task goal_type.
    conn.exec_driver_sql(
        """
        CREATE TABLE goals__new (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            phase_id INTEGER NOT NULL REFERENCES phases(id) ON DELETE CASCADE,
            title VARCHAR(250) NOT NULL,
            note TEXT,
            owner_participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE RESTRICT,
            weight FLOAT NOT NULL DEFAULT 1.0,
            milestone_date DATE NOT NULL,
            deadline DATE NOT NULL,
            goal_type VARCHAR(20) NOT NULL DEFAULT 'requirement',
            requirement_priority INTEGER,
            issue_module VARCHAR(120),
            issue_total_di FLOAT,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            CONSTRAINT ck_goals_weight_positive CHECK (weight > 0),
            CONSTRAINT ck_goals_status CHECK (status in ('active', 'completed')),
            CONSTRAINT ck_goals_goal_type CHECK (goal_type in ('requirement', 'issue', 'task')),
            CONSTRAINT ck_goals_requirement_priority CHECK (
                requirement_priority is null or (requirement_priority >= 1 and requirement_priority <= 5)
            ),
            CONSTRAINT ck_goals_issue_total_di_positive CHECK (issue_total_di is null or issue_total_di > 0)
        )
        """
    )
    conn.exec_driver_sql(
        """
        INSERT INTO goals__new (
            id, phase_id, title, note, owner_participant_id, weight, milestone_date, deadline,
            goal_type, requirement_priority, issue_module, issue_total_di, status
        )
        SELECT
            id, phase_id, title, note, owner_participant_id, weight, milestone_date, deadline,
            goal_type, requirement_priority, issue_module, issue_total_di, status
        FROM goals
        """
    )
    conn.exec_driver_sql("DROP TABLE goals")
    conn.exec_driver_sql("ALTER TABLE goals__new RENAME TO goals")


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
