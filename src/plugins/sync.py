"""
Plugin sync — syncs plugins from filesystem to database
"""

import logging
from typing import List

from src.db.entity import DBPlugin
from src.db.repository import DBRepository
from src.plugins.registry import get_plugin_registry

logger = logging.getLogger(__name__)


def sync_plugins_to_database() -> List[DBPlugin]:
    """
    Scan plugins folder, register all in database.

    This should be called on application startup.
    Returns list of registered/updated plugins.
    """
    from src.db.database import engine
    from src.db.entity import DBPlugin as EntityPlugin

    registry = get_plugin_registry()
    plugins_metadata = registry.get_plugins_metadata()

    synced = []

    with engine.connect() as conn:
        for metadata in plugins_metadata:
            plugin_id = metadata["id"]

            # Check if exists
            existing = conn.execute(
                f"SELECT id FROM plugins WHERE id = '{plugin_id}'"
            ).fetchone()

            if existing:
                # Update
                logger.info(f"Plugin {plugin_id} already in DB")
            else:
                # Insert
                import uuid
                from datetime import datetime

                plugin = EntityPlugin(
                    id=plugin_id,
                    name=metadata["name"],
                    description=metadata["description"],
                    version=metadata["version"],
                    plugin_path=f"plugins/{plugin_id}",
                    input_model=metadata["input_model"],
                    output_model=metadata["output_model"],
                    parameters_schema=metadata["parameters_schema"],
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

                from sqlalchemy.orm import Session
                with Session(engine) as session:
                    session.add(plugin)
                    session.commit()
                    logger.info(f"Synced plugin {plugin_id} to database")

            synced.append(plugin_id)

    return synced


def get_plugins_from_database() -> List[dict]:
    """Get all plugins from database"""
    repo = DBRepository()
    db_plugins = repo.get_all_plugins(active_only=True)

    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "version": p.version,
            "plugin_path": p.plugin_path,
            "input_model": p.input_model,
            "output_model": p.output_model,
            "parameters_schema": p.parameters_schema,
        }
        for p in db_plugins
    ]
