"""
Tests for Docker module
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


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
        # If Docker is not available, is_available returns False
        # If available, returns True
        result = client.is_available()

        # This test passes if Docker is available or not
        assert isinstance(result, bool)

    @patch('docker.from_env')
    def test_docker_client_connection_error(self, mock_from_env):
        """Should handle connection error gracefully"""
        import docker.errors

        mock_from_env.side_effect = docker.errors.DockerException("Connection refused")

        # Reset singleton for test
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


class TestDockerTemplates:
    """Tests for Dockerfile templates"""

    def test_base_dockerfile_template(self):
        """Should return base Dockerfile template"""
        from src.docker.templates import BASE_DOCKERFILE

        assert "python:3.12-slim" in BASE_DOCKERFILE
        assert "ffmpeg" in BASE_DOCKERFILE
        assert "requirements.txt" in BASE_DOCKERFILE

    def test_get_dockerfile_for_plugin(self):
        """Should return Dockerfile for plugin"""
        from src.docker.templates import get_dockerfile_for_plugin

        dockerfile = get_dockerfile_for_plugin("media_converter")

        assert "python:3.12-slim" in dockerfile
        assert "ffmpeg" in dockerfile

    def test_get_requirements_for_media_converter(self):
        """Should return correct requirements for media_converter"""
        from src.docker.templates import get_requirements_for_plugin

        requirements = get_requirements_for_plugin("media_converter")

        assert "pydantic" in requirements
        assert "pydub" in requirements

    def test_get_requirements_for_llm_request(self):
        """Should return correct requirements for llm_request"""
        from src.docker.templates import get_requirements_for_plugin

        requirements = get_requirements_for_plugin("llm_request")

        assert "pydantic" in requirements
        assert "openai" in requirements

    def test_get_requirements_for_speech_to_text(self):
        """Should return correct requirements for speech_to_text"""
        from src.docker.templates import get_requirements_for_plugin

        requirements = get_requirements_for_plugin("speech_to_text")

        assert "pydub" in requirements
        assert "openai" in requirements


class TestFastBuild:
    """Tests for Fast Build"""

    def test_fast_build_initialization(self):
        """Should initialize with Docker client"""
        from src.docker.fast_build import FastBuild

        mock_docker = MagicMock()
        fb = FastBuild(docker_client=mock_docker)

        assert fb.docker is mock_docker

    def test_compute_files_hash(self):
        """Should compute consistent hash for files"""
        from src.docker.fast_build import FastBuild
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "file1.py"
            file1.write_text("content1")

            file2 = Path(tmpdir) / "file2.py"
            file2.write_text("content2")

            hash1 = FastBuild._compute_files_hash([file1])
            hash2 = FastBuild._compute_files_hash([file1, file2])

            assert hash1 != hash2
            assert len(hash1) == 16

    def test_cache_invalid_after_ttl(self):
        """Should invalidate cache after TTL"""
        from src.docker.fast_build import FastBuild
        import time

        mock_docker = MagicMock()
        fb = FastBuild(docker_client=mock_docker)

        # Without actual cache, should return False
        result = fb._is_cache_valid("nonexistent_plugin", ttl_seconds=3600)
        assert result is False

    def test_clear_cache(self):
        """Should clear build cache"""
        from src.docker.fast_build import FastBuild

        mock_docker = MagicMock()
        fb = FastBuild(docker_client=mock_docker)

        # Should not raise
        fb.clear_cache()
        fb.clear_cache("test_plugin")


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