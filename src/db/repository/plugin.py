from typing import Optional, List

from src.db.repository.base import BaseRepository
from src.db.entity import DBPlugin
from src.db.models.node_template import PluginModel


def _plugin_to_model(plugin: DBPlugin) -> PluginModel:
    def _dt(v):
        return v.isoformat() if v else None

    return PluginModel(
        id=plugin.id,
        name=plugin.name,
        description=plugin.description,
        version=plugin.version,
        plugin_path=plugin.plugin_path,
        input_model=plugin.input_model,
        output_model=plugin.output_model,
        parameters_schema=plugin.parameters_schema,
        docker_image=plugin.docker_image,
        is_active=plugin.is_active,
        created_at=_dt(plugin.created_at),
        updated_at=_dt(plugin.updated_at),
    )


class PluginRepository(BaseRepository):

    def create(self, data: dict) -> PluginModel:
        with self.session() as s:
            plugin = DBPlugin(**data)
            s.add(plugin)
            s.commit()
            s.refresh(plugin)
            return _plugin_to_model(plugin)

    def get(self, plugin_id: str) -> Optional[PluginModel]:
        with self.session() as s:
            plugin = s.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()
            if not plugin:
                return None
            return _plugin_to_model(plugin)

    def get_all(self, active_only: bool = True) -> List[PluginModel]:
        with self.session() as s:
            query = s.query(DBPlugin)
            if active_only:
                query = query.filter(DBPlugin.is_active == True)
            return [_plugin_to_model(p) for p in query.all()]

    def update(self, plugin_id: str, **kwargs) -> Optional[PluginModel]:
        with self.session() as s:
            plugin = s.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()
            if not plugin:
                return None
            for key, value in kwargs.items():
                setattr(plugin, key, value)
            s.commit()
            s.refresh(plugin)
            return _plugin_to_model(plugin)
