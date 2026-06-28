"""
Plugin runner for Docker container execution

Reads input.json and .manifest.json, executes plugin, writes output.json
"""

import asyncio
import json
import os
import sys

from pathlib import Path

from prometheus_client import push_to_gateway, REGISTRY

from src.plugins.registry import PluginRegistry
from src.plugins.base import PluginContext
from src.plugins.datasource import DataSourceManifest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    input_path = os.environ.get("PLUGIN_INPUT", "/input/input.json")
    manifest_path = os.path.join(os.path.dirname(input_path), ".manifest.json")
    output_path = os.environ.get("PLUGIN_OUTPUT", "/output/output.json")
    plugin_id_env = os.environ.get("PLUGIN_ID", "")
    execution_id_env = os.environ.get("EXECUTION_ID", "")
    pushgateway_url = os.environ.get("PUSHGATEWAY_URL", "")

    with open(input_path, "r") as f:
        input_data = json.load(f)

    plugin_id = input_data.pop("__plugin_id", None) or plugin_id_env
    parameters = input_data.pop("__parameters", {})

    if not plugin_id:
        raise ValueError("__plugin_id not found in input")

    registry = PluginRegistry()
    registry.scan_plugins_folder()
    plugin_class = registry.get_plugin(plugin_id)

    if not plugin_class:
        raise ValueError(f"Plugin not found: {plugin_id}")

    plugin = plugin_class()
    
    manifest = DataSourceManifest.from_path(manifest_path) or DataSourceManifest()

    context = PluginContext(
        execution_id=input_data.get("execution_id", "") or execution_id_env,
        node_id=input_data.get("node_id", ""),
        manifest=manifest,
    )

    result = asyncio.run(plugin.execute(context, parameters))

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result.model_dump(), f)

    print(f"Plugin {plugin_id} executed successfully")

    if pushgateway_url:
        try:
            push_to_gateway(
                pushgateway_url,
                job=f"plugin_{plugin_id}",
                registry=REGISTRY,
                grouping_key={
                    "plugin_id": plugin_id,
                    "execution_id": execution_id_env or "unknown"
                }
            )
            print(f"Metrics pushed to Pushgateway: {pushgateway_url}")
        except Exception as e:
            print(f"Warning: Failed to push metrics to Pushgateway: {e}")


if __name__ == "__main__":
    main()
