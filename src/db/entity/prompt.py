from datetime import datetime

from sqlalchemy import Column, String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBPrompt(Base):
    __tablename__ = "prompts"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=True)
    user_prompt_template = Column(Text, nullable=True)
    variables = Column(JSON, nullable=True)
    minio_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("DBUser", back_populates="prompts")
    node_templates = relationship("DBNodeTemplate", back_populates="prompt")
