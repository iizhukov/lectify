"""
Plugin Docker Image Manager — builds plugin images on startup if they don't exist.
"""
import subprocess
from pathlib import Path
from typing import Dict, List

from src.utils.logging import get_logger

logger = get_logger(__name__)


def _get_docker_executable() -> str:
    return "docker"


def _image_exists(image_name: str) -> bool:
    """Check if Docker image exists locally."""
    try:
        result = subprocess.run(
            [_get_docker_executable(), "image", "inspect", image_name],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _build_image(
    image_name: str,
    dockerfile_path: str,
    build_args: Dict[str, str],
    context_path: str,
) -> bool:
    """
    Build a Docker image.

    Args:
        image_name: Target image name (e.g. lectify-plugin-media_converter)
        dockerfile_path: Path to Dockerfile
        build_args: Build args for docker build --build-arg
        context_path: Docker build context directory
    """
    try:
        cmd = [
            _get_docker_executable(),
            "build",
            "-t", image_name,
            "-f", dockerfile_path,
        ]
        for key, value in build_args.items():
            cmd += ["--build-arg", f"{key}={value}"]
        cmd.append(context_path)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(
                "docker_build_failed",
                image=image_name,
                stderr=result.stderr,
            )
            return False

        logger.info("docker_build_succeeded", image=image_name)
        return True

    except FileNotFoundError:
        logger.warning("docker_not_found_skip_build", image=image_name)
        return False
    except Exception as e:
        logger.error("docker_build_error", image=image_name, error=str(e))
        return False


def _get_plugin_requirements(plugin_dir: Path) -> Path | None:
    """
    Return path to requirements.txt inside a plugin directory if it exists.
    Falls back to project root requirements.txt.
    """
    req = plugin_dir / "requirements.txt"
    if req.exists():
        return req
    return None


def _prepare_build_context(
    plugin_dir: Path,
    plugin_dockerfile: Path,
    project_root: Path,
    plugin_id: str,
) -> Path:
    """
    Copy only necessary files for plugin runtime into a temp build context directory.

    This creates a minimal context containing:
    - Plugin runtime files (base.py, registry.py, runner.py)
    - Specific plugin code
    - Minimal utils (storage, logging)
    - Minimal db module
    - LLM client
    - Config file

    Returns path to the build context directory.
    """
    import tempfile
    import shutil

    context_dir = Path(tempfile.mkdtemp(prefix=f"lectify-plugin-build-{plugin_id}-"))

    # Copy only necessary src files (not entire src/)
    def copy_if_exists(src_path: Path, dest_path: Path):
        """Copy file or directory if it exists"""
        if src_path.exists():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if src_path.is_dir():
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                shutil.copy2(src_path, dest_path)

    # Copy config module (needed by storage, db, llm)
    copy_if_exists(
        project_root / "src" / "config.py",
        context_dir / "src" / "config.py"
    )

    # Plugin runtime files
    plugin_runtime_files = [
        "src/plugins/__init__.py",
        "src/plugins/base.py",
        "src/plugins/registry.py",
        "src/plugins/runner.py",
    ]
    for file_path in plugin_runtime_files:
        copy_if_exists(
            project_root / file_path,
            context_dir / file_path
        )

    # Create empty __init__.py for plugins directory
    # (avoid cross-plugin imports that would fail in isolated container)
    plugins_init = context_dir / "src" / "plugins" / "plugins" / "__init__.py"
    plugins_init.parent.mkdir(parents=True, exist_ok=True)
    plugins_init.write_text("")

    # Copy specific plugin directory
    copy_if_exists(
        plugin_dir,
        context_dir / "src" / "plugins" / "plugins" / plugin_id
    )

    # Copy utils (storage, logging, metrics)
    utils_files = [
        "src/utils/storage.py",
        "src/utils/logging.py",
        "src/utils/metrics.py",
    ]
    for file_path in utils_files:
        copy_if_exists(
            project_root / file_path,
            context_dir / file_path
        )

    # Copy db module (for plugins that need DB access)
    db_files = [
        "src/db/__init__.py",
        "src/db/database.py",
    ]
    for file_path in db_files:
        copy_if_exists(
            project_root / file_path,
            context_dir / file_path
        )

    # Copy db/entity directory (contains all entity definitions)
    copy_if_exists(
        project_root / "src" / "db" / "entity",
        context_dir / "src" / "db" / "entity"
    )

    # Copy db/models directory (if exists)
    copy_if_exists(
        project_root / "src" / "db" / "models",
        context_dir / "src" / "db" / "models"
    )

    # Copy llm client (for plugins using OpenAI API)
    copy_if_exists(
        project_root / "src" / "llm",
        context_dir / "src" / "llm"
    )

    # Copy config.cfg
    copy_if_exists(
        project_root / "config.cfg",
        context_dir / "config.cfg"
    )

    # Copy project-level requirements
    shutil.copy2(project_root / "requirements.txt", context_dir / "requirements.txt")

    # Copy plugin-specific requirements if present (overwrites project-level)
    req = _get_plugin_requirements(plugin_dir)
    if req:
        shutil.copy2(req, context_dir / "requirements.txt")

    # Copy Dockerfile
    shutil.copy2(plugin_dockerfile, context_dir / "Dockerfile")

    return context_dir


def build_missing_plugin_images(
    plugins_dir: Path | None = None,
    project_root: Path | None = None,
    required_plugins: List[str] | None = None,
    rebuild: bool = False,
) -> Dict[str, bool]:
    """
    Build Docker images for plugins that don't have a local image yet.

    Called on application startup.

    Args:
        plugins_dir: Path to src/plugins/plugins/ (auto-detected if None)
        project_root: Path to project root (auto-detected if None)
        required_plugins: If provided, only build these plugin IDs.
                          Otherwise build all discovered plugins.
        rebuild: If True, delete existing images and rebuild them.

    Returns:
        Dict mapping plugin_id -> build success (True) or failure (False)
    """
    if plugins_dir is None:
        plugins_dir = Path(__file__).parent / "plugins"
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    plugin_dockerfile = Path(__file__).parent / "docker" / "Dockerfile.plugin"

    if not plugin_dockerfile.exists():
        logger.warning("plugin_dockerfile_not_found", path=str(plugin_dockerfile))
        return {}

    if required_plugins is None:
        required_plugins = _discover_plugins(plugins_dir)

    results: Dict[str, bool] = {}

    for plugin_id in required_plugins:
        image_name = f"lectify-plugin-{plugin_id}"

        if _image_exists(image_name):
            if not rebuild:
                logger.info("plugin_image_exists", image=image_name)
                results[plugin_id] = True
                continue
            logger.info("plugin_image_rebuilding", image=image_name)
            _remove_image(image_name)
        else:
            logger.info("plugin_image_missing_building", image=image_name)
        plugin_dir = plugins_dir / plugin_id

        if not plugin_dir.exists():
            logger.warning("plugin_dir_not_found_skip", plugin_id=plugin_id)
            results[plugin_id] = False
            continue

        context_dir = _prepare_build_context(
            plugin_dir,
            plugin_dockerfile,
            project_root,
            plugin_id,
        )

        try:
            ok = _build_image(
                image_name=image_name,
                dockerfile_path=str(context_dir / "Dockerfile"),
                build_args={"PLUGIN_ID": plugin_id},
                context_path=str(context_dir),
            )
            results[plugin_id] = ok
        finally:
            # Cleanup temp context
            import shutil as _shutil
            try:
                _shutil.rmtree(context_dir)
            except Exception:
                pass

    return results


def _remove_image(image_name: str) -> None:
    """Remove a Docker image by name."""
    try:
        subprocess.run(
            [_get_docker_executable(), "rmi", "-f", image_name],
            capture_output=True,
            text=True,
        )
    except Exception as e:
        logger.warning("docker_rmi_failed", image=image_name, error=str(e))


def _discover_plugins(plugins_dir: Path) -> List[str]:
    """Return list of plugin IDs (directory names) in plugins_dir."""
    if not plugins_dir.exists():
        return []
    return [
        d.name
        for d in plugins_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_")
    ]
