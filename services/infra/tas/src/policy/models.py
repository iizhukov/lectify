from enum import Enum
from dataclasses import dataclass, field


class PermissionEffect(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"

    @classmethod
    def from_proto(cls, value: int) -> "PermissionEffect":
        mapping = {1: cls.ALLOW, 2: cls.DENY}
        return mapping.get(value, cls.DENY)

    def to_proto(self) -> int:
        mapping = {self.ALLOW: 1, self.DENY: 2}
        return mapping.get(self, 0)


@dataclass
class PermissionRule:
    source_service: str
    target_service: str
    effect: PermissionEffect = PermissionEffect.ALLOW
    description: str = ""
    is_default: bool = False  # True if loaded from service.yaml
