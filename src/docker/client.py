"""
Docker Client — wrapper around docker-py SDK
"""

import logging
import tempfile
import shutil
from pathlib import Path
from typing import Optional

import docker
from docker.models.containers import Container
from docker.types import Mount

logger = logging.getLogger(__name__)


class DockerClient:
    """
    Singleton Docker client wrapper.
    """

    _instance: Optional["DockerClient"] = None
    _client: Optional[docker.DockerClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._plugin_registry = None
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        try:
            self._client = docker.from_env()
            self._client.ping()
            logger.info("Docker connection established")
            self._initialized = True
        except docker.errors.DockerException as e:
            logger.error(f"Docker connection failed: {e}")
            self._client = None

    @property
    def client(self) -> Optional[docker.DockerClient]:
        """Get Docker client or None if not connected"""
        return self._client

    def is_available(self) -> bool:
        """Check if Docker is available"""
        return self._client is not None

    def pull_image(self, image: str, tag: str = "latest") -> bool:
        """Pull Docker image"""
        if not self._client:
            return False

        try:
            logger.info(f"Pulling image: {image}:{tag}")
            self._client.images.pull(image, tag)
            return True
        except Exception as e:
            logger.error(f"Failed to pull image {image}:{tag}: {e}")
            return False

    def build_image(
        self,
        path: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        buildargs: dict = None,
        nocache: bool = False
    ) -> Optional[str]:
        """Build Docker image from directory"""
        if not self._client:
            return None

        try:
            logger.info(f"Building image: {tag}")
            image, logs = self._client.images.build(
                path=path,
                tag=tag,
                dockerfile=dockerfile,
                buildargs=buildargs or {},
                rm=True,
                nocache=nocache
            )
            for log in logs:
                if "stream" in log:
                    logger.debug(log["stream"].strip())
            return image.id
        except Exception as e:
            logger.error(f"Failed to build image {tag}: {e}")
            return None

    def _get_plugin_image_tag(self, plugin_id: str) -> str:
        """Return the canonical image name for a plugin."""
        return f"lectify-plugin-{plugin_id}"

    def _get_registry_tag(self, plugin_id: str, registry: str) -> str:
        """Return the fully-qualified registry tag for a plugin."""
        return f"{registry}/lectify-plugin-{plugin_id}"

    def _pull_plugin_image(self, plugin_id: str, registry: str) -> bool:
        """Pull a plugin image from a remote registry."""
        full_tag = self._get_registry_tag(plugin_id, registry)
        try:
            logger.info(f"Pulling plugin image from registry: {full_tag}")
            self._client.images.pull(registry, plugin_id)
            # Tag as local name
            local_tag = self._get_plugin_image_tag(plugin_id)
            self._client.images.get(full_tag).tag(local_tag)
            logger.info(f"Pulled and tagged as {local_tag}")
            return True
        except Exception as e:
            logger.debug(f"Could not pull {full_tag}: {e}")
            return False

    def _push_plugin_image(self, plugin_id: str, registry: str) -> bool:
        """Push a plugin image to a remote registry."""
        local_tag = self._get_plugin_image_tag(plugin_id)
        full_tag = self._get_registry_tag(plugin_id, registry)
        try:
            # Tag for registry
            self._client.images.get(local_tag).tag(registry, plugin_id)
            logger.info(f"Pushing {full_tag}")
            for line in self._client.images.push(registry, plugin_id, stream=True, decode=True):
                if "error" in line:
                    raise Exception(line.get("error", str(line)))
            logger.info(f"Pushed: {full_tag}")
            return True
        except Exception as e:
            logger.warning(f"Failed to push {full_tag}: {e}")
            return False

    def _ensure_plugin_image(self, plugin_id: str, push: bool = False) -> bool:
        """
        Check if plugin image exists locally. If not, pull from registry or build.

        Args:
            plugin_id: Plugin identifier.
            push: If True and registry is configured, push after building.

        Returns True if the image is available, False otherwise.
        """
        image_name = self._get_plugin_image_tag(plugin_id)

        # Fast path: image already exists locally
        if self._image_exists_locally(image_name):
            logger.debug(f"Plugin image already exists: {image_name}")
            return True

        # Try registry pull first (fastest path if registry is configured)
        try:
            from src.config import config
            registry = config.plugins_registry
        except Exception:
            registry = ""

        if registry:
            if self._pull_plugin_image(plugin_id, registry):
                return True

        # Build locally
        logger.info(f"Building plugin image locally: {image_name}")

        plugin_dockerfile = (
            Path(__file__).parent.parent
            / "plugins" / "docker" / "Dockerfile.plugin"
        )
        if not plugin_dockerfile.exists():
            logger.error(
                f"Plugin dockerfile not found: plugin_id={plugin_id}, path={plugin_dockerfile}",
            )
            return False

        plugin_src_dir = (
            Path(__file__).parent.parent
            / "plugins" / "plugins" / plugin_id
        )
        if not plugin_src_dir.exists():
            logger.error(
                f"Plugin source dir not found: plugin_id={plugin_id}, path={plugin_src_dir}",
            )
            return False

        project_root = Path(__file__).parent.parent.parent
        context_dir = self._prepare_plugin_context(
            plugin_id=plugin_id,
            plugin_src_dir=plugin_src_dir,
            plugin_dockerfile=plugin_dockerfile,
            project_root=project_root,
        )

        try:
            success = self.build_image(
                path=str(context_dir),
                tag=image_name,
                dockerfile="Dockerfile",
                buildargs={"PLUGIN_ID": plugin_id},
                nocache=False,
            )
            if success:
                logger.info(f"Plugin image built: {image_name}")
                if push and registry:
                    self._push_plugin_image(plugin_id, registry)
            else:
                logger.error(f"Plugin image build failed: {plugin_id}")
            return bool(success)

        finally:
            try:
                shutil.rmtree(context_dir)
            except Exception:
                pass

    def _prepare_plugin_context(
        self,
        plugin_id: str,
        plugin_src_dir: Path,
        plugin_dockerfile: Path,
        project_root: Path,
    ) -> Path:
        """Build a temp directory with all files needed for the Docker build."""
        context_dir = Path(tempfile.mkdtemp(prefix=f"lectify-plugin-build-{plugin_id}-"))

        # Copy project source
        shutil.copytree(
            project_root / "src",
            context_dir / "src",
            dirs_exist_ok=True,
        )

        # Copy project-level requirements
        shutil.copy2(project_root / "requirements.txt", context_dir / "requirements.txt")

        # Copy plugin-specific requirements (overrides project-level)
        plugin_req = plugin_src_dir / "requirements.txt"
        if plugin_req.exists():
            shutil.copy2(plugin_req, context_dir / "requirements.txt")

        # Copy plugin source into expected location
        plugin_dest = context_dir / "src" / "plugins" / "plugins" / plugin_id
        shutil.copytree(plugin_src_dir, plugin_dest, dirs_exist_ok=True)

        # Copy config.cfg (needed by storage/db/llm connections in container)
        config_cfg = project_root / "config.cfg"
        if config_cfg.exists():
            shutil.copy2(config_cfg, context_dir / "config.cfg")

        # Get system packages from plugin class
        system_packages = self._get_plugin_system_packages(plugin_id)

        # Generate Dockerfile with plugin-specific system packages
        self._generate_plugin_dockerfile(
            context_dir / "Dockerfile",
            plugin_dockerfile,
            plugin_id,
            system_packages
        )

        return context_dir

    def _get_plugin_system_packages(self, plugin_id: str) -> list:
        """Load plugin class and extract system_packages"""
        try:
            from src.plugins.registry import PluginRegistry
            if self._plugin_registry is None:
                self._plugin_registry = PluginRegistry()
                self._plugin_registry.scan_plugins_folder()
            plugin_class = self._plugin_registry.get_plugin(plugin_id)
            if plugin_class and hasattr(plugin_class, 'system_packages'):
                return plugin_class.system_packages or []
        except Exception as e:
            logger.warning(f"Could not load system_packages for {plugin_id}: {e}")
        return []

    def _generate_plugin_dockerfile(
        self,
        output_path: Path,
        base_dockerfile: Path,
        plugin_id: str,
        system_packages: list
    ):
        """Generate Dockerfile with plugin-specific system packages"""
        with open(base_dockerfile, "r") as f:
            base_content = f.read()

        if not system_packages:
            with open(output_path, "w") as f:
                f.write(base_content)
            return

        lines = base_content.split("\n")
        new_lines = []
        i = 0

        while i < len(lines):
            line = lines[i]

            if "RUN apt-get update" in line and "apt-get install" in line:
                apt_lines = [line]
                j = i + 1
                while j < len(lines) and (apt_lines[-1].rstrip().endswith("\\") or apt_lines[-1].rstrip().endswith("&&")):
                    apt_lines.append(lines[j])
                    j += 1

                insert_idx = len(apt_lines) - 1
                for idx, apt_line in enumerate(apt_lines):
                    if "rm -rf" in apt_line:
                        insert_idx = idx
                        break

                for pkg in system_packages:
                    apt_lines.insert(insert_idx, f"    {pkg} \\")
                    insert_idx += 1

                new_lines.extend(apt_lines)
                i = j
            else:
                new_lines.append(line)
                i += 1

        with open(output_path, "w") as f:
            f.write("\n".join(new_lines))

    def build_plugin_image(self, plugin_id: str, push: bool = False) -> bool:
        """
        Public API: build a plugin image, regardless of whether it already exists.
        Optionally push to registry after building.

        Args:
            plugin_id: Plugin identifier.
            push: If True and registry is configured, push after building.
        """
        image_name = self._get_plugin_image_tag(plugin_id)
        if self._image_exists_locally(image_name):
            logger.info(f"Removing existing image before rebuild: {image_name}")
            try:
                self._client.images.remove(image_name)
            except Exception as e:
                logger.warning(f"Failed to remove old image {image_name}: {e}")
        return self._ensure_plugin_image(plugin_id, push=push)

    def _image_exists_locally(self, image_name: str) -> bool:
        """Check if an image exists in the local Docker daemon."""
        try:
            self._client.images.get(image_name)
            return True
        except docker.errors.ImageNotFound:
            return False
        except Exception:
            return False

    def create_container(
        self,
        image: str,
        command: str = None,
        volumes: dict = None,
        environment: dict = None,
        network: str = None,
        mem_limit: str = "512m",
        cpu_period: int = 100000,
        cpu_quota: int = 50000
    ) -> Optional[Container]:
        """Create a Docker container"""
        if not self._client:
            return None

        if image.startswith("lectify-plugin-"):
            plugin_id = image.replace("lectify-plugin-", "")
            if not self._ensure_plugin_image(plugin_id):
                logger.error(f"Plugin image unavailable: {image}")
                return None

        mounts = []
        if volumes:
            for composite_key, config in volumes.items():
                # composite_key = "host_path:container_target"
                container_target = config.get("bind", "")
                mode = config.get("mode", "rw")
                # host_path = everything before the last ":" (the container target)
                host_path = composite_key.rsplit(":", 1)[0]
                mounts.append(Mount(
                    target=container_target,
                    source=host_path,
                    type="bind",
                    read_only=(mode == "ro")
                ))

        try:
            container = self._client.containers.run(
                image,
                command=command,
                mounts=mounts,
                environment=environment,
                network=network,
                mem_limit=mem_limit,
                cpu_period=cpu_period,
                cpu_quota=cpu_quota,
                extra_hosts={"host.docker.internal": "host-gateway"},
                detach=True,
                remove=False
            )
            logger.info(f"Container created: {container.id[:12]}")
            return container
        except Exception as e:
            logger.error(f"Failed to create container: {e}")
            # Try to cleanup any partially created container
            try:
                # Extract container ID from error message if available
                error_str = str(e)
                if "container" in error_str.lower():
                    # List recent containers that might have been created
                    recent_containers = self._client.containers.list(
                        all=True,
                        filters={"ancestor": image},
                        limit=5
                    )
                    for c in recent_containers:
                        if c.status in ["created", "exited"]:
                            # Remove containers that were created but failed to start
                            try:
                                c.remove(force=True)
                                logger.info(f"Cleaned up failed container: {c.id[:12]}")
                            except:
                                pass
            except:
                pass
            return None

    def get_container(self, container_id: str) -> Optional[Container]:
        """Get container by ID"""
        if not self._client:
            return None

        try:
            return self._client.containers.get(container_id)
        except docker.errors.NotFound:
            return None

    def stop_container(self, container_id: str, timeout: int = 10) -> bool:
        """Stop a container"""
        if not self._client:
            return False

        try:
            container = self._client.containers.get(container_id)
            container.stop(timeout=timeout)
            logger.info(f"Container stopped: {container_id[:12]}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop container {container_id[:12]}: {e}")
            return False

    def remove_container(self, container_id: str, force: bool = False) -> bool:
        """Remove a container"""
        if not self._client:
            return False

        try:
            container = self._client.containers.get(container_id)
            container.remove(force=force)
            logger.info(f"Container removed: {container_id[:12]}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove container {container_id[:12]}: {e}")
            return False

    def get_container_stats(
        self,
        container_id: str
    ) -> Optional[dict]:
        """Get container stats (CPU, memory)"""
        if not self._client:
            return None

        try:
            container = self._client.containers.get(container_id)
            stats = container.stats(stream=False)

            # Calculate CPU percentage
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_count = stats["cpu_stats"].get("online_cpus", 1)
            cpu_percent = (cpu_delta / system_delta * cpu_count * 100) if system_delta > 0 else 0

            # Memory
            memory_usage = stats["memory_stats"].get("usage", 0)
            memory_limit = stats["memory_stats"].get("limit", 1)
            memory_percent = (memory_usage / memory_limit * 100) if memory_limit > 0 else 0

            return {
                "cpu_percent": min(cpu_percent, 100),
                "memory_mb": memory_usage / (1024 * 1024),
                "memory_percent": min(memory_percent, 100)
            }
        except Exception as e:
            logger.error(f"Failed to get stats for {container_id[:12]}: {e}")
            return None

    def get_container_logs(
        self,
        container_id: str,
        tail: int = 100
    ) -> str:
        """Get container logs"""
        if not self._client:
            return ""

        try:
            container = self._client.containers.get(container_id)
            logs = container.logs(stdout=True, stderr=True, tail=tail)
            return logs.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to get logs for {container_id[:12]}: {e}")
            return ""


# Global instance
_docker_client: Optional[DockerClient] = None


def get_docker_client() -> DockerClient:
    """Get global Docker client instance"""
    global _docker_client
    if _docker_client is None:
        _docker_client = DockerClient()
    return _docker_client
