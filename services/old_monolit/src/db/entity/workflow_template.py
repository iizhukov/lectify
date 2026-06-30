from datetime import datetime

from sqlalchemy import Column, String, Text, Boolean, ForeignKey, DateTime, JSON, Integer
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBWorkflowTemplate(Base):
    __tablename__ = "workflow_templates"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    graph = Column(JSON, nullable=False)
    is_public = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("DBUser", back_populates="workflow_templates")
    executions = relationship("DBExecution", back_populates="workflow_template")


class DBWorkflowPublic(Base):
    __tablename__ = "workflows_public"

    id = Column(String, primary_key=True)
    original_workflow_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    graph = Column(JSON, nullable=False)
    author_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    usage_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    author = relationship("DBUser")
