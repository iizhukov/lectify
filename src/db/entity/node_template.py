from datetime import datetime

from sqlalchemy import Column, String, Text, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBNodeTemplate(Base):
    __tablename__ = "node_templates"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    plugin_id = Column(String, ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    parameters = Column(JSON, nullable=False, default=dict)
    input_mapping = Column(JSON, nullable=True)
    prompt_id = Column(String, ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("DBUser", back_populates="node_templates")
    plugin = relationship("DBPlugin", back_populates="node_templates")
    prompt = relationship("DBPrompt", back_populates="node_templates")
    execution_nodes = relationship("DBExecutionNode", back_populates="node_template")
