#!/usr/bin/env python3
"""
Build plugin Docker images.

Usage:
    python scripts/build_plugins.py              # build all plugins
    python scripts/build_plugins.py latex_to_pdf  # build specific plugin
    python scripts/build_plugins.py --rebuild   # rebuild all from scratch
    python scripts/build_plugins.py --fat       # use fat images (layer caching)

This script should be run:
    - After adding a new plugin
    - After changing system_packages in a plugin
    - After updating plugin dependencies
"""
import argparse
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from tqdm import tqdm

from src.docker.client import DockerClient
from src.plugins.registry import PluginRegistry
from src.config import config


def main():
    parser = argparse.ArgumentParser(description="Build Lectify plugin Docker images")
    parser.add_argument(
        "plugins",
        nargs="*",
        default=[],
        help="Plugin IDs to build (default: all discovered plugins)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild even if image already exists",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push images to configured registry after building",
    )
    parser.add_argument(
        "--fat",
        action="store_true",
        default=None,
        help="Use fat Docker images (larger, but faster builds via layer caching). "
             "Overrides config.cfg setting.",
    )
    args = parser.parse_args()

    registry = PluginRegistry()
    registry.scan_plugins_folder()

    if args.plugins:
        plugin_ids = args.plugins
    else:
        plugin_ids = list(registry.get_all_plugins().keys())

    if not plugin_ids:
        print("No plugins found.")
        return

    fat = args.fat if args.fat is not None else config.plugins_fat_images
    if fat:
        print("Using fat Docker images (layer caching enabled)\n")

    print(f"Building {len(plugin_ids)} plugin(s): {plugin_ids}\n")

    client = DockerClient()

    passed = 0
    failed = 0

    for plugin_id in tqdm(plugin_ids, desc="Building plugins", unit="plugin"):
        try:
            if args.rebuild:
                success = client.build_plugin_image(plugin_id, push=args.push, fat=fat)
            else:
                success = client._ensure_plugin_image(plugin_id, push=args.push, fat=fat)
            if success:
                passed += 1
            else:
                tqdm.write(f"  [FAIL] {plugin_id}")
                failed += 1
        except Exception as e:
            tqdm.write(f"  [ERROR] {plugin_id} — {e}")
            failed += 1

    print(f"\nDone: {passed} ok, {failed} failed")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
