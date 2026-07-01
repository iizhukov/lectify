from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, Text, Boolean, JSON, DateTime, Integer
from sqlalchemy.orm import relationship

from src.db.entity.base import Base


class DBPlugin(Base):
    __tablename__ = "plugins"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    version = Column(String, nullable=False)
    plugin_path = Column(String, nullable=False)
    input_model = Column(String, nullable=False)
    output_model = Column(String, nullable=False)
    parameters_schema = Column(JSON, nullable=True)
    color = Column(String, nullable=True)
    icon_svg = Column(Text, nullable=True)
    docker_image = Column(String, nullable=True)
    node_count = Column(Integer, nullable=True)  # DEPRECATED: computed from len(node_templates)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    node_templates = relationship("DBNodeTemplate", back_populates="plugin")
