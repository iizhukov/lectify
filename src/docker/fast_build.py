"""
Fast Docker build — quick image building with caching
"""

import logging
import tempfile
import time
from pathlib import Path
from typing import Optional

from src.docker.client import DockerClient, get_docker_client
from src.docker.templates import get_dockerfile_for_plugin, get_requirements_for_plugin


logger = logging.getLogger(__name__)

_image_cache: dict = {}


class FastBuild:
    """
    Fast Docker image builder with caching.

    Strategy:
    1. Use base image as parent (python:3.12-slim)
    2. Layer caching: requirements.txt -> code
    3. Only rebuild if files changed
    """

    def __init__(self, docker_client: DockerClient = None):
        self.docker = docker_client or get_docker_client()
        self._build_cache_dir = Path(tempfile.gettempdir()) / "lectify" / "builds"
        self._build_cache_dir.mkdir(parents=True, exist_ok=True)

    def build_plugin_image(
        self,
        plugin_id: str,
        plugin_path: Path = None,
        force_rebuild: bool = False
    ) -> Optional[str]:
        """
        Build plugin Docker image.

        Returns image tag or None if failed.
        """
        image_tag = f"lectify-plugin-{plugin_id}:latest"

        # Check cache (valid for 1 hour by default)
        if not force_rebuild and self._is_cache_valid(plugin_id):
            logger.info(f"Using cached image for {plugin_id}")
            return image_tag

        # Build new image
        logger.info(f"Building image for {plugin_id}")

        try:
            # Create temp build directory
            build_dir = self._build_cache_dir / plugin_id
            build_dir.mkdir(parents=True, exist_ok=True)

            # Generate Dockerfile
            dockerfile_content = get_dockerfile_for_plugin(plugin_id, str(plugin_path or ""))
            (build_dir / "Dockerfile").write_text(dockerfile_content)

            # Generate requirements.txt
            requirements_content = get_requirements_for_plugin(plugin_id)
            (build_dir / "requirements.txt").write_text(requirements_content)

            # Copy plugin code if path provided
            if plugin_path and plugin_path.exists():
                import shutil
                for item in plugin_path.iterdir():
                    if item.name not in ["docker", "__pycache__"]:
                        if item.is_dir():
                            shutil.copytree(item, build_dir / item.name, dirs_exist_ok=True)
                        elif item.suffix != ".pyc":
                            shutil.copy2(item, build_dir / item.name)

            # Build image
            image_id = self.docker.build_image(
                path=str(build_dir),
                tag=image_tag,
                dockerfile="Dockerfile"
            )

            if image_id:
                # Update cache
                _image_cache[plugin_id] = {
                    "timestamp": time.time(),
                    "image_id": image_id
                }
                logger.info(f"Built image {image_tag} ({image_id[:12]})")
                return image_tag
            else:
                logger.error(f"Failed to build image for {plugin_id}")
                return None

        except Exception as e:
            logger.error(f"Build failed for {plugin_id}: {e}")
            return None

    def _is_cache_valid(self, plugin_id: str, ttl_seconds: int = 3600) -> bool:
        """Check if cached image is still valid"""
        if plugin_id not in _image_cache:
            return False

        cache_entry = _image_cache[plugin_id]
        age = time.time() - cache_entry["timestamp"]

        if age > ttl_seconds:
            return False

        # Verify image exists
        try:
            image_tag = f"lectify-plugin-{plugin_id}:latest"
            self.docker.client.images.get(image_tag)
            return True
        except:
            return False

    def rebuild_if_needed(
        self,
        plugin_id: str,
        plugin_path: Path = None,
        source_files: list = None
    ) -> Optional[str]:
        """
        Rebuild image only if source files changed.

        Args:
            plugin_id: Plugin ID
            plugin_path: Path to plugin source
            source_files: List of source file paths to check
        """
        if source_files is None and plugin_path:
            source_files = []
            for item in plugin_path.rglob("*"):
                if item.is_file() and item.suffix == ".py":
                    source_files.append(item)

        # Check file hashes
        cache_key = f"{plugin_id}_hash"
        current_hash = self._compute_files_hash(source_files or [])

        cached_hash = _image_cache.get(cache_key, {}).get("hash")
        if cached_hash == current_hash and self._is_cache_valid(plugin_id):
            logger.debug(f"Using cached image for {plugin_id} (no changes)")
            return f"lectify-plugin-{plugin_id}:latest"

        # Rebuild
        image_tag = self.build_plugin_image(plugin_id, plugin_path, force_rebuild=True)

        if image_tag:
            _image_cache[cache_key] = {"hash": current_hash}

        return image_tag

    @staticmethod
    def _compute_files_hash(files: list) -> str:
        """Compute hash of all files"""
        import hashlib

        hasher = hashlib.sha256()
        for filepath in sorted(files):
            try:
                content = filepath.read_bytes()
                hasher.update(content)
            except:
                pass

        return hasher.hexdigest()[:16]

    def clear_cache(self, plugin_id: str = None):
        """Clear build cache"""
        if plugin_id:
            _image_cache.pop(plugin_id, None)
        else:
            _image_cache.clear()

        logger.info(f"Build cache cleared for {plugin_id or 'all'}")


def get_fast_build() -> FastBuild:
    """Get FastBuild instance"""
    return FastBuild()
