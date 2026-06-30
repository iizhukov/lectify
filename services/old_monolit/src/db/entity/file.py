from datetime import datetime

from sqlalchemy import Column, String, ForeignKey, DateTime, Integer, Text
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBFile(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    original_path = Column(String, nullable=False)
    language = Column(String, nullable=False)
    status = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)
    minio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    workflows = relationship(
        "DBWorkflow",
        back_populates="file",
        cascade="all, delete-orphan"
    )


class DBWorkflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    final_artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)

    file = relationship("DBFile", back_populates="workflows")
    nodes = relationship(
        "DBWorkflowNode",
        back_populates="workflow",
        cascade="all, delete-orphan"
    )


class DBWorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id = Column(String, primary_key=True)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String, nullable=False)
    node_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    artifact_path = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    workflow = relationship("DBWorkflow", back_populates="nodes")
    artifacts = relationship(
        "DBArtifact",
        back_populates="node",
        cascade="all, delete-orphan"
    )
    dependencies = relationship(
        "DBWorkflowNodeDependency",
        foreign_keys="DBWorkflowNodeDependency.node_db_id",
        cascade="all, delete-orphan"
    )


class DBWorkflowNodeDependency(Base):
    __tablename__ = "workflow_node_dependencies"

    id = Column(String, primary_key=True)
    node_db_id = Column(String, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False)
    dependency_node_id = Column(String, nullable=False)


class DBArtifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True)
    file_id = Column(String, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    node_id = Column(String, ForeignKey("workflow_nodes.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    ext = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    path = Column(String, nullable=False)
    minio_path = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    node = relationship("DBWorkflowNode", back_populates="artifacts")
