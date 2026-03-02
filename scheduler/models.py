from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    participants: Mapped[list[Participant]] = relationship(back_populates="project", cascade="all, delete-orphan")
    phases: Mapped[list[Phase]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("project_id", "email", name="uq_participants_project_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False)

    project: Mapped[Project] = relationship(back_populates="participants")
    owned_goals: Mapped[list[Goal]] = relationship(back_populates="owner")
    account: Mapped[Optional[UserAccount]] = relationship(back_populates="participant", uselist=False)


class Phase(Base):
    __tablename__ = "phases"
    __table_args__ = (UniqueConstraint("project_id", "order_index", name="uq_phases_project_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    project: Mapped[Project] = relationship(back_populates="phases")
    goals: Mapped[list[Goal]] = relationship(back_populates="phase", cascade="all, delete-orphan")


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (
        CheckConstraint("weight > 0", name="ck_goals_weight_positive"),
        CheckConstraint("status in ('active', 'completed')", name="ck_goals_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    owner_participant_id: Mapped[int] = mapped_column(ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    milestone_date: Mapped[date] = mapped_column(Date, nullable=False)
    deadline: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    phase: Mapped[Phase] = relationship(back_populates="goals")
    owner: Mapped[Participant] = relationship(back_populates="owned_goals")
    progress_updates: Mapped[list[GoalProgressUpdate]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class GoalProgressUpdate(Base):
    __tablename__ = "goal_progress_updates"
    __table_args__ = (
        UniqueConstraint("goal_id", "date", name="uq_goal_progress_goal_date"),
        CheckConstraint("progress_percent >= 0 and progress_percent <= 100", name="ck_progress_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    goal: Mapped[Goal] = relationship(back_populates="progress_updates")


class ReminderLog(Base):
    __tablename__ = "reminder_logs"
    __table_args__ = (
        UniqueConstraint(
            "goal_id",
            "date",
            "reminder_type",
            "recipient",
            name="uq_reminder_goal_date_type_recipient",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    recipient: Mapped[str] = mapped_column(String(200), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class ReportRecord(Base):
    __tablename__ = "report_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    markdown_path: Mapped[str] = mapped_column(String(500), nullable=False)
    emailed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("username", name="uq_user_accounts_username"),
        UniqueConstraint("participant_id", name="uq_user_accounts_participant_id"),
        CheckConstraint("role in ('admin', 'owner')", name="ck_user_accounts_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    participant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("participants.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    participant: Mapped[Optional[Participant]] = relationship(back_populates="account")
