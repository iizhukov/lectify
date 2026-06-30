from unittest.mock import MagicMock, patch


class TestDockerClient:
    """Tests for Docker client"""

    def test_docker_client_singleton(self):
        """DockerClient should be a singleton"""
        from src.docker.client import DockerClient

        c1 = DockerClient()
        c2 = DockerClient()

        assert c1 is c2

    def test_docker_client_availability_check(self):
        """Should check Docker availability"""
        from src.docker.client import DockerClient

        client = DockerClient()
        result = client.is_available()

        assert isinstance(result, bool)

    @patch('docker.from_env')
    def test_docker_client_connection_error(self, mock_from_env):
        """Should handle connection error gracefully"""
        import docker.errors

        mock_from_env.side_effect = docker.errors.DockerException("Connection refused")

        from src.docker import client as docker_module
        docker_module.DockerClient._instance = None
        docker_module.DockerClient._client = None

        client = docker_module.DockerClient()

        assert client.is_available() is False


class TestContainerRunner:
    """Tests for Container Runner"""

    def test_runner_initialization(self):
        """Should initialize with Docker client"""
        from src.docker.runner import ContainerRunner

        mock_docker = MagicMock()
        runner = ContainerRunner(docker_client=mock_docker)

        assert runner.docker is mock_docker

    def test_runner_with_minio_client(self):
        """Should accept MinIO client"""
        from src.docker.runner import ContainerRunner

        mock_docker = MagicMock()
        mock_minio = MagicMock()

        runner = ContainerRunner(
            docker_client=mock_docker,
            minio_client=mock_minio
        )

        assert runner.docker is mock_docker
        assert runner.minio_client is mock_minio


class TestContainerMetrics:
    """Tests for Container Metrics"""

    def test_metrics_initialization(self):
        """Should initialize with default values"""
        from src.docker.runner import ContainerMetrics

        metrics = ContainerMetrics()

        assert metrics.cpu_percent == 0
        assert metrics.memory_mb == 0
        assert metrics.execution_time_ms == 0
        assert metrics.logs == ""

    def test_metrics_update(self):
        """Should allow metrics updates"""
        from src.docker.runner import ContainerMetrics

        metrics = ContainerMetrics()
        metrics.cpu_percent = 50.5
        metrics.memory_mb = 256.0
        metrics.execution_time_ms = 5000
        metrics.logs = "Some logs"

        assert metrics.cpu_percent == 50.5
        assert metrics.memory_mb == 256.0
        assert metrics.execution_time_ms == 5000
        assert metrics.logs == "Some logs"


class TestPollingContainerRunner:
    """Tests for Polling Container Runner"""

    def test_runner_initialization(self):
        """Should initialize polling runner"""
        from src.docker.runner import PollingContainerRunner

        mock_docker = MagicMock()
        runner = PollingContainerRunner(docker_client=mock_docker)

        assert runner.docker is mock_docker
        assert runner._poll_thread is None
        assert runner._latest_metrics is None

    def test_stop_polling_flag(self):
        """Should have stop polling event"""
        from src.docker.runner import PollingContainerRunner

        mock_docker = MagicMock()
        runner = PollingContainerRunner(docker_client=mock_docker)

        assert runner._stop_polling is not None
        assert runner._stop_polling.is_set() is False
