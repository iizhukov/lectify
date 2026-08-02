from typing import Optional
from sqlalchemy import select, delete

from generated.db.connection import get_session_factory
from generated.logger import get_logger

from src.models import PermissionRuleModel
from src.policy.models import PermissionRule, PermissionEffect
from src.policy.loader import load_default_rules


class PermissionStore:
    def __init__(self) -> None:
        self._rules: dict[tuple[str, str], PermissionRule] = {}
        self._loaded = False
        self._log = None

    @property
    def log(self):
        if self._log is None:
            
            self._log = get_logger("permission_store")
        return self._log

    async def load_defaults(self, repo_root: str | None = None) -> None:
        root = None
        if repo_root:
            root = __import__("pathlib").Path(repo_root)
        
        rules = load_default_rules(root)
        for rule in rules:
            key = (rule.source_service, rule.target_service)
            if key not in self._rules:
                self._rules[key] = rule
                self.log.info("permission_default_loaded",
                              source=rule.source_service,
                              target=rule.target_service)

        await self._load_custom_from_db()

        self._loaded = True
        self.log.info("permission_defaults_loaded", count=len(rules))

    async def _load_custom_from_db(self) -> None:
        try:
            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(select(PermissionRuleModel))

                for row in result.scalars().all():
                    effect = PermissionEffect.ALLOW if row.effect == "ALLOW" else PermissionEffect.DENY
                    rule = PermissionRule(
                        source_service=row.source_service,
                        target_service=row.target_service,
                        effect=effect,
                        description=row.description or "",
                        is_default=False,
                    )
                    key = (rule.source_service, rule.target_service)
                    self._rules[key] = rule
                    self.log.info(
                        "permission_custom_loaded",
                        source=rule.source_service,
                        target=rule.target_service
                    )
                    
        except Exception as e:
            self.log.warning("permission_custom_load_failed", error=str(e))

    async def set_rule(
        self,
        source: str,
        target: str,
        effect: PermissionEffect,
        description: str = ""
    ) -> None:
        rule = PermissionRule(
            source_service=source,
            target_service=target,
            effect=effect,
            description=description,
            is_default=False,
        )
        key = (source, target)
        self._rules[key] = rule

        await self._persist_rule(source, target, effect.value, description)

        self.log.info(
            "permission_set",
            source=source,
            target=target,
            effect=effect.value
        )

    async def remove_rule(self, source: str, target: str) -> bool:
        key = (source, target)
        if key not in self._rules:
            return False

        existing = self._rules[key]
        if existing.is_default:
            del self._rules[key]

            defaults = load_default_rules()
            for d in defaults:
                if d.source_service == source and d.target_service == target:
                    self._rules[key] = d
                    break
        else:
            del self._rules[key]

        await self._remove_from_db(source, target)

        self.log.info("permission_removed", source=source, target=target)
        return True

    async def check_permission(self, source: str, target: str) -> bool:
        rule = self._rules.get((source, target))
        if rule is None:
            return False
        return rule.effect == PermissionEffect.ALLOW

    async def check_permission_full(self, source: str, target: str) -> tuple[bool, Optional[PermissionEffect]]:
        rule = self._rules.get((source, target))

        if rule is None:
            return False, None
        
        return rule.effect == PermissionEffect.ALLOW, rule.effect

    def list_rules(self) -> list[PermissionRule]:
        return list(self._rules.values())

    async def _persist_rule(
        self,
        source: str,
        target: str,
        effect: str,
        description: str
    ) -> None:
        try:
            factory = get_session_factory()
            async with factory() as session:
                result = await session.execute(
                    select(PermissionRuleModel).where(
                        PermissionRuleModel.source_service == source,
                        PermissionRuleModel.target_service == target,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing:
                    existing.effect = effect
                    existing.description = description
                else:
                    session.add(PermissionRuleModel(
                        source_service=source,
                        target_service=target,
                        effect=effect,
                        description=description,
                    ))
                await session.commit()
        except Exception as e:
            self.log.warning("permission_persist_failed", error=str(e))

    async def _remove_from_db(self, source: str, target: str) -> None:
        try:
            factory = get_session_factory()
            async with factory() as session:
                await session.execute(
                    delete(PermissionRuleModel).where(
                        PermissionRuleModel.source_service == source,
                        PermissionRuleModel.target_service == target,
                    )
                )
                await session.commit()
        except Exception as e:
            self.log.warning("permission_remove_db_failed", error=str(e))


_store: PermissionStore | None = None


async def get_permission_store() -> PermissionStore:
    global _store

    if _store is None:
        _store = PermissionStore()
        await _store.load_defaults()

    return _store


def reset_permission_store() -> None:
    global _store
    _store = None
