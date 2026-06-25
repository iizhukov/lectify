"""
Docker Client — wrapper around docker-py SDK
"""

import logging
from typing import Optional

import docker
from docker.models.containers import Container

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
        buildargs: dict = None
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
                rm=True
            )
            for log in logs:
                if "stream" in log:
                    logger.debug(log["stream"].strip())
            return image.id
        except Exception as e:
            logger.error(f"Failed to build image {tag}: {e}")
            return None

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

        try:
            container = self._client.containers.run(
                image,
                command=command,
                volumes=volumes,
                environment=environment,
                network=network,
                mem_limit=mem_limit,
                cpu_period=cpu_period,
                cpu_quota=cpu_quota,
                detach=True,
                remove=False
            )
            logger.info(f"Container created: {container.id[:12]}")
            return container
        except Exception as e:
            logger.error(f"Failed to create container: {e}")
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
