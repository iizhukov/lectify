import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Integer,
    BigInteger,
    Boolean,
    DateTime,
    Text,
    JSON,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from generated.db.base import BaseModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowExecutionModel(BaseModel):
    __tablename__ = "workflow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    graph_json: Mapped[dict] = mapped_column(JSON, default=dict)
    initial_inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    total_progress: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    nodes: Mapped[list["WorkflowNodeExecutionModel"]] = relationship(
        "WorkflowNodeExecutionModel",
        back_populates="execution",
        cascade="all, delete-orphan",
    )


class WorkflowNodeExecutionModel(BaseModel):
    __tablename__ = "workflow_node_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(String(36), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plugin_id: Mapped[str] = mapped_column(String(64), nullable=False)
    plugin_version: Mapped[str] = mapped_column(String(32), default="0.1.0")
    state: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    progress_message: Mapped[str] = mapped_column(String(256), default="")
    bytes_streamed_in: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes_streamed_out: Mapped[int] = mapped_column(BigInteger, default=0)
    chunks_processed: Mapped[int] = mapped_column(Integer, default=0)
    execution_time_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    output_artifacts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    execution: Mapped["WorkflowExecutionModel"] = relationship(
        "WorkflowExecutionModel",
        back_populates="nodes",
    )


class PluginRegistryModel(BaseModel):
    __tablename__ = "plugin_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="general")
    description: Mapped[str] = mapped_column(Text, default="")
    manifest_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkflowDispatchModel(BaseModel):
    __tablename__ = 'workflow_dispatch'

    execution_id: Mapped[str] = mapped_column(
        ForeignKey('workflow_executions.id', ondelete='CASCADE'), primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(32), default='PENDING', nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    report_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_token_fence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class NodeEventModel(BaseModel):
    __tablename__ = 'workflow_node_events'
    __table_args__ = (
        UniqueConstraint('execution_id', 'event_id', name='uq_workflow_node_event_id'),
        Index('ix_workflow_node_events_execution_sequence', 'execution_id', 'sequence'),
    )
    sequence: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, 'sqlite'), primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ContainerAttemptModel(BaseModel):
    __tablename__ = 'workflow_container_attempts'
    __table_args__ = (UniqueConstraint('execution_id', 'node_id', 'fence', 'role',
        name='uq_workflow_container_assignment'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False)
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    image: Mapped[str] = mapped_column(String(512), nullable=False)
    daemon_id: Mapped[str] = mapped_column(String(256), nullable=False)
    state: Mapped[str] = mapped_column(String(24), default='PREPARED', nullable=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
