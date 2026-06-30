"""
Plugins package — contains all available plugins
"""

from src.plugins.base import Plugin, PluginContext, PluginParameter
from src.plugins.registry import (
    PluginRegistry,
    get_plugin_registry,
    scan_and_register_plugins
)

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginParameter",
    "PluginRegistry",
    "get_plugin_registry",
    "scan_and_register_plugins",
]
