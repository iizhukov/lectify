"""
Plugin Registry — scans plugins folder and registers plugins
"""

import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

from src.plugins.base import Plugin, PluginContext

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Registry for all available plugins.

    Scans the plugins directory at startup and registers
    all classes that inherit from Plugin.
    """

    _instance: Optional["PluginRegistry"] = None
    _plugins: Dict[str, Type[Plugin]] = {}
    _plugins_metadata: Dict[str, dict] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._plugins = {}
        self._plugins_metadata = {}
        self._initialized = True

    def register(self, plugin_class: Type[Plugin]):
        """Register a plugin class"""
        plugin_id = plugin_class.id
        if not plugin_id:
            raise ValueError(f"Plugin {plugin_class.__name__} has no id")

        if plugin_id in self._plugins:
            logger.warning(f"Plugin {plugin_id} already registered, overwriting")

        self._plugins[plugin_id] = plugin_class

        # Build parameters schema - handle both list and FieldInfo cases
        params = plugin_class.parameters_schema
        if params is None:
            params_schema = []
        elif isinstance(params, list):
            params_schema = [p.model_dump() if hasattr(p, 'model_dump') else p for p in params]
        else:
            params_schema = []

        inputs = [f for f in plugin_class.input_model.model_fields if f != "file_id"]
        outputs = list(plugin_class.output_model.model_fields.keys())

        self._plugins_metadata[plugin_id] = {
            "id": plugin_id,
            "name": plugin_class.name,
            "description": plugin_class.description,
            "version": plugin_class.version,
            "category": getattr(plugin_class, "category", "general"),
            "color": getattr(plugin_class, "color", "#9ca3af"),
            "icon_svg": getattr(plugin_class, "icon_svg", ""),
            "input_model": plugin_class.input_model.__name__,
            "output_model": plugin_class.output_model.__name__,
            "parameters_schema": params_schema,
            "inputs": inputs,
            "outputs": outputs,
        }
        logger.info(f"Registered plugin: {plugin_id}")

    def scan_plugins_folder(self, plugins_dir: str = None):
        """
        Scan plugins folder and register all plugins.

        Expected structure:
            plugins/
                __init__.py
                media_converter/
                    __init__.py  (or plugin.py)
                    models.py
                llm_request/
                    __init__.py
                    models.py
        """
        if plugins_dir is None:
            plugins_dir = Path(__file__).parent / "plugins"

        plugins_dir = Path(plugins_dir)
        if not plugins_dir.exists():
            logger.warning(f"Plugins directory not found: {plugins_dir}")
            return

        logger.info(f"Scanning plugins folder: {plugins_dir}")

        # Add plugins directory to path
        if str(plugins_dir.parent) not in sys.path:
            sys.path.insert(0, str(plugins_dir.parent))

        # Scan each plugin subdirectory
        for item in plugins_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith("_"):
                continue

            plugin_path = item.name

            # Try to import plugin module
            try:
                module_name = f"plugins.{plugin_path}"
                module = importlib.import_module(module_name)

                # Find all Plugin subclasses in the module
                for name, obj in inspect.getmembers(module):
                    if (
                        inspect.isclass(obj)
                        and issubclass(obj, Plugin)
                        and obj != Plugin
                        and obj.id  # Must have an ID
                    ):
                        self.register(obj)

            except Exception as e:
                logger.error(f"Failed to load plugin {plugin_path}: {e}")
                import traceback
                traceback.print_exc()

    def get_plugin(self, plugin_id: str) -> Optional[Type[Plugin]]:
        """Get plugin class by ID"""
        return self._plugins.get(plugin_id)

    def get_all_plugins(self) -> Dict[str, Type[Plugin]]:
        """Get all registered plugins"""
        return self._plugins.copy()

    def get_plugins_by_category(self, category: str) -> Dict[str, Type[Plugin]]:
        """Get plugins filtered by category"""
        return {
            pid: pclass
            for pid, pclass in self._plugins.items()
            if getattr(pclass, "category", "general") == category
        }

    def get_plugins_metadata(self) -> List[dict]:
        """Get metadata for all plugins (for UI)"""
        return list(self._plugins_metadata.values())

    def get_plugin_metadata(self, plugin_id: str) -> Optional[dict]:
        """Get metadata for a specific plugin"""
        return self._plugins_metadata.get(plugin_id)


# Global registry instance
registry = PluginRegistry()


def get_plugin_registry() -> PluginRegistry:
    """Get the global plugin registry"""
    return registry


def scan_and_register_plugins(plugins_dir: str = None):
    """Scan plugins folder and register all plugins"""
    registry.scan_plugins_folder(plugins_dir)