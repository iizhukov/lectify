from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    String,
    ForeignKey,
    DateTime,
    Integer,
    Text
)

from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    relationship
)


import os

# PostgreSQL connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://lectify:lectify_password@localhost:5432/lectify"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


class DBFile(Base):
    __tablename__ = "files"

    id = Column(String, primary_key=True, index=True)

    filename = Column(String, nullable=False)
    original_path = Column(String, nullable=False)

    language = Column(String, nullable=False)

    status = Column(String, nullable=False)

    size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    workflows = relationship(
        "DBWorkflow",
        back_populates="file",
        cascade="all, delete-orphan"
    )


class DBWorkflow(Base):
    __tablename__ = "workflows"

    id = Column(String, primary_key=True)

    file_id = Column(
        String,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False
    )

    name = Column(String, nullable=False)

    status = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    final_artifact_id = Column(
        String,
        ForeignKey("artifacts.id", ondelete="SET NULL"),
        nullable=True
    )

    file = relationship(
        "DBFile",
        back_populates="workflows"
    )

    nodes = relationship(
        "DBWorkflowNode",
        back_populates="workflow",
        cascade="all, delete-orphan"
    )


class DBWorkflowNode(Base):
    __tablename__ = "workflow_nodes"

    id = Column(String, primary_key=True)

    workflow_id = Column(
        String,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False
    )

    file_id = Column(
        String,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False
    )

    node_id = Column(String, nullable=False)
    node_name = Column(String, nullable=False)

    status = Column(String, nullable=False)

    message = Column(Text, nullable=True)
    artifact_path = Column(Text, nullable=True)

    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)

    workflow = relationship(
        "DBWorkflow",
        back_populates="nodes"
    )

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

    node_db_id = Column(
        String,
        ForeignKey("workflow_nodes.id", ondelete="CASCADE"),
        nullable=False
    )

    dependency_node_id = Column(String, nullable=False)


class DBArtifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True)

    file_id = Column(
        String,
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False
    )

    workflow_id = Column(
        String,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False
    )

    node_id = Column(
        String,
        ForeignKey("workflow_nodes.id", ondelete="CASCADE"),
        nullable=False
    )

    name = Column(String, nullable=False)
    ext = Column(String, nullable=False)

    mime_type = Column(String, nullable=False)

    path = Column(String, nullable=False)  # Локальный путь (для обратной совместимости)
    minio_path = Column(String, nullable=True)  # Путь в MinIO

    size_bytes = Column(Integer, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    node = relationship(
        "DBWorkflowNode",
        back_populates="artifacts"
    )


def init_sqlalchemy_db():
    Base.metadata.create_all(bind=engine)
