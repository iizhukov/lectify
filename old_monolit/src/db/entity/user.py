from datetime import datetime

from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBUser(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    username = Column(String, nullable=False, unique=True, index=True)
    email = Column(String, nullable=True, unique=True, index=True)
    password_hash = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node_templates = relationship("DBNodeTemplate", back_populates="user")
    workflow_templates = relationship("DBWorkflowTemplate", back_populates="user")
    prompts = relationship("DBPrompt", back_populates="user")
    executions = relationship("DBExecution", back_populates="user")
    sessions = relationship("DBSession", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("DBPasswordResetToken", back_populates="user", cascade="all, delete-orphan")
