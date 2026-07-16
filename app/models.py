from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.state import ActualState, DesiredState, JobStatus, WorkerStatus


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="user", nullable=False)

    resources: Mapped[list["Resource"]] = relationship(back_populates="user")
    api_tokens: Mapped[list["ApiToken"]] = relationship(back_populates="user")


class ApiToken(TimestampMixin, Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), default="default", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="api_tokens")


class Template(TimestampMixin, Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    exposed_port: Mapped[int] = mapped_column(Integer, default=8000, nullable=False)
    default_cpu: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    default_memory_mb: Mapped[int] = mapped_column(Integer, default=128, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    resources: Mapped[list["Resource"]] = relationship(back_populates="template")


class Resource(TimestampMixin, Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("slug", name="uq_resources_slug"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    desired_state: Mapped[str] = mapped_column(
        String(50),
        default=DesiredState.RUNNING.value,
        nullable=False,
    )
    actual_state: Mapped[str] = mapped_column(
        String(50),
        default=ActualState.PENDING.value,
        nullable=False,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cpu_limit: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    memory_mb: Mapped[int] = mapped_column(Integer, default=128, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="resources")
    template: Mapped[Template] = relationship(back_populates="resources")
    jobs: Mapped[list["Job"]] = relationship(back_populates="resource")
    events: Mapped[list["Event"]] = relationship(back_populates="resource")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claimable", "status", "available_at", "created_at"),
        Index("ix_jobs_resource_status", "resource_id", "status"),
        Index(
            "uq_jobs_one_running_per_resource",
            "resource_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=JobStatus.QUEUED.value,
        index=True,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    claimed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resource: Mapped[Resource] = relationship(back_populates="jobs")


class Worker(TimestampMixin, Base):
    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    process_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default=WorkerStatus.RUNNING.value,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
        nullable=False,
    )
    current_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id"),
        nullable=True,
    )


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True, nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_metadata: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )

    resource: Mapped[Resource] = relationship(back_populates="events")
