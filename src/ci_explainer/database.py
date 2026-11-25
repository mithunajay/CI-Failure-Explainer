"""SQLAlchemy models and persistence helpers for accounts and analyses."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from .log_cleaner import clean_log


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email", "email", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    password_salt: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_purpose: Mapped[str | None] = mapped_column(String(16), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    otp_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    otp_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    analyses: Mapped[list[Analysis]] = relationship(back_populates="user")


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_user_created", "user_id", "created_at"),
        Index("ix_analyses_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    log: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[dict] = mapped_column(JSON, nullable=False)
    user: Mapped[User] = relationship(back_populates="analyses")


def create_database_engine(url: str):
    return create_engine(url, pool_pre_ping=True)


def initialize_database(engine) -> None:
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("users")}
    additions = (
        ("email", "VARCHAR(254) NULL"),
        ("email_verified", "BOOLEAN NOT NULL DEFAULT 0"),
        ("otp_hash", "VARCHAR(64) NULL"),
        ("otp_purpose", "VARCHAR(16) NULL"),
        ("otp_expires_at", "DATETIME NULL"),
        ("otp_requested_at", "DATETIME NULL"),
        ("otp_attempts", "INTEGER NOT NULL DEFAULT 0"),
    )
    with engine.begin() as connection:
        for name, definition in additions:
            if name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )
    indexes = {index["name"] for index in inspect(engine).get_indexes("users")}
    if "uq_users_email" not in indexes:
        next(index for index in User.__table__.indexes if index.name == "uq_users_email").create(
            engine, checkfirst=True
        )


def save_analysis(session: Session, user: dict, raw_log: str, explanation: dict) -> int:
    cleaned = clean_log(raw_log)
    record = Analysis(
        user_id=user["id"],
        username=user["username"],
        log=cleaned.text,
        explanation=explanation,
    )
    session.add(record)
    session.commit()
    return record.id


def list_analyses(
    session: Session, user_id: int | None = None, limit: int = 50
) -> list[Analysis]:
    statement = select(Analysis).order_by(Analysis.created_at.desc()).limit(limit)
    if user_id is not None:
        statement = statement.where(Analysis.user_id == user_id)
    return list(session.scalars(statement))


def list_accounts(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.username)))
