from sqlalchemy import Boolean, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from generated.db.base import BaseModel


class Workflow(BaseModel):
    __tablename__ = 'workflow_templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(4096), nullable=False)
    graph: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class NodeTemplate(BaseModel):
    __tablename__ = 'workflow_node_templates'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    plugin_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plugin_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(4096), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_mapping: Mapped[list] = mapped_column(JSON, nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkflowSnapshot(BaseModel):
    __tablename__ = 'workflow_snapshots'
    __table_args__ = (UniqueConstraint('created_by', 'request_key', name='uq_workflow_snapshot_request'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Deliberately no FK to a mutable/deletable template.
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(4096), nullable=False)
    graph: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
