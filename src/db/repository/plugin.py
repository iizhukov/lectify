from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.entity import DBPlugin


class PluginRepository(BaseRepository):

    def create(self, data: dict) -> DBPlugin:
        with self.session() as s:
            plugin = DBPlugin(**data)
            s.add(plugin)
            s.commit()
            s.refresh(plugin)
            return plugin

    def get(self, plugin_id: str) -> Optional[DBPlugin]:
        with self.session() as s:
            return s.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()

    def get_all(self, active_only: bool = True):
        with self.session() as s:
            query = s.query(DBPlugin)
            if active_only:
                query = query.filter(DBPlugin.is_active == True)
            return query.all()

    def update(self, plugin_id: str, **kwargs) -> Optional[DBPlugin]:
        with self.session() as s:
            plugin = s.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()
            if not plugin:
                return None
            for key, value in kwargs.items():
                setattr(plugin, key, value)
            s.commit()
            s.refresh(plugin)
            return plugin
