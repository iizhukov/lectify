from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

from generated.db.base import BaseModel


class RevokedTicket(BaseModel):
    __tablename__ = "revoked_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    jti = Column(String(255), nullable=False, unique=True, index=True)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now())
    reason = Column(String(255), nullable=True)


class PermissionRuleModel(BaseModel):
    __tablename__ = "permission_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_service = Column(String(255), nullable=False)
    target_service = Column(String(255), nullable=False)
    effect = Column(String(16), nullable=False, default="ALLOW")  # ALLOW | DENY
    description = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
