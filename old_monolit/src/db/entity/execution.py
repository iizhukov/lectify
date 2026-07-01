from datetime import datetime

from sqlalchemy import Column, String, Text, ForeignKey, DateTime, JSON, Float, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.orm import relationship

from src.db.entity.base import Base, ExecutionStatus, NodeExecutionStatus


class DBExecution(Base):
    __tablename__ = "executions"

    id = Column(String, primary_key=True)
    workflow_template_id = Column(String, ForeignKey("workflow_templates.id", ondelete="SET NULL"), nullable=True)
    file_id = Column(String, nullable=True)  # deprecated, для single-file workflows
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    workflow_name = Column(String, nullable=True)  # human-readable execution name
    file_name = Column(String, nullable=True)  # input file name
    language = Column(String, nullable=True, default="ru")  # language for the execution
    input_files = Column(JSON, nullable=True)  # {node_id: file_id} для множественных входов
    status = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    workflow_template = relationship("DBWorkflowTemplate", back_populates="executions")
    user = relationship("DBUser", back_populates="executions")
    nodes = relationship("DBExecutionNode", back_populates="execution", cascade="all, delete-orphan")


class DBExecutionNode(Base):
    __tablename__ = "execution_nodes"

    id = Column(String, primary_key=True)
    execution_id = Column(String, ForeignKey("executions.id", ondelete="CASCADE"), nullable=False)
    node_template_id = Column(String, ForeignKey("node_templates.id", ondelete="SET NULL"), nullable=True)
    node_id = Column(String, nullable=False)
    plugin_id = Column(String, nullable=True)  # which plugin this node runs
    node_name = Column(String, nullable=True)  # human-readable node label
    status = Column(String, nullable=False)
    progress_percent = Column(Integer, nullable=True)
    progress_message = Column(Text, nullable=True)
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    container_id = Column(String, nullable=True)
    cpu_percent = Column(Float, nullable=True)
    memory_mb = Column(Float, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    logs_path = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    execution = relationship("DBExecution", back_populates="nodes")
    node_template = relationship("DBNodeTemplate", back_populates="execution_nodes")
