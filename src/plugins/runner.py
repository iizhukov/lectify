"""
Plugin runner for Docker container execution

Reads input.json, executes plugin, writes output.json
"""

import json
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def main():
    """Main entry point for plugin container"""
    input_path = os.environ.get("PLUGIN_INPUT", "/input/input.json")
    output_path = os.environ.get("PLUGIN_OUTPUT", "/output/output.json")

    # Read input
    with open(input_path, "r") as f:
        input_data = json.load(f)

    plugin_id = input_data.pop("__plugin_id", None)
    parameters = input_data.pop("__parameters", {})

    if not plugin_id:
        raise ValueError("__plugin_id not found in input")

    # Import and execute plugin
    from src.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    registry.scan_plugins_folder()
    plugin_class = registry.get_plugin(plugin_id)

    if not plugin_class:
        raise ValueError(f"Plugin not found: {plugin_id}")

    plugin = plugin_class()

    # Create context (no MinIO in Docker for now)
    from src.plugins.base import PluginContext
    context = PluginContext(
        execution_id=input_data.get("execution_id", ""),
        node_id=input_data.get("node_id", "")
    )

    # Parse input
    input_model = plugin.input_model(**input_data)

    # Execute
    import asyncio
    result = asyncio.run(plugin.execute(input_model, context, parameters))

    # Write output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result.model_dump(), f)

    print(f"Plugin {plugin_id} executed successfully")


if __name__ == "__main__":
    main()
