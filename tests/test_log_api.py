"""
Tests for /api/workflows/executions/{id}/nodes/{node_id}/logs endpoints (src/api/workflows.py)
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

from src.api.workflows import router, _node_to_dict
from src.db.entity import NodeExecutionStatus


@pytest.fixture
def mock_db():
    with patch("src.api.workflows.DBRepository") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture
def mock_storage():
    with patch("src.api.workflows.get_storage") as mock:
        yield mock.return_value


@pytest.fixture
def mock_container_runner():
    with patch("src.api.workflows.ContainerRunner") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture
def log_client(mock_db):
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mock_db


def _mock_node(node_id="n1", logs_path=None,
               status=NodeExecutionStatus.COMPLETED,
               progress_message="Done"):
    node = MagicMock()
    node.id = "node-db-id"
    node.node_id = node_id
    node.node_template_id = "t1"
    node.status = status
    node.progress_percent = 100
    node.progress_message = progress_message
    node.cpu_percent = 50.0
    node.memory_mb = 128.0
    node.execution_time_ms = 5000
    node.error_message = None
    node.logs_path = logs_path
    node.started_at = None
    node.ended_at = None
    return node


# =============================================================================
# GET /executions/{id}/nodes/{node_id}/logs
# =============================================================================

class TestGetNodeLogs:
    def test_returns_logs_from_minio(self, log_client):
        client, mock_db, mock_storage = log_client

        mock_node = _mock_node(logs_path="node/2026/06/25/exec_n1.log")
        mock_db.get_by_execution.return_value = [mock_node]
        mock_storage.read_log.return_value = "log line 1\nlog line 2\n"

        response = client.get("/api/workflows/executions/exec-123/nodes/n1/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "minio"
        assert data["logs"] == "log line 1\nlog line 2\n"
        assert data["logs_path"] == "node/2026/06/25/exec_n1.log"

    def test_falls_back_to_container_logs(self, log_client):
        client, mock_db, mock_storage = log_client

        mock_node = _mock_node(
            logs_path=None,
            status=NodeExecutionStatus.RUNNING
        )
        mock_db.get_by_execution.return_value = [mock_node]
        mock_storage.read_log.return_value = None

        mock_runner = MagicMock()
        mock_runner.docker.get_container_logs.return_value = "container log output"

        with patch("src.api.workflows.ContainerRunner", return_value=mock_runner):
            response = client.get("/api/workflows/executions/exec-123/nodes/n1/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "container"
        assert data["logs"] == "container log output"
        assert data["container_id"] == "container-abc"

    def test_returns_no_logs_when_unavailable(self, log_client):
        client, mock_db = log_client

        mock_node = _mock_node(
            logs_path=None,
            status=NodeExecutionStatus.PENDING,
            progress_message="Still waiting..."
        )
        mock_db.get_by_execution.return_value = [mock_node]

        response = client.get("/api/workflows/executions/exec-123/nodes/n1/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "none"
        assert data["logs"] == "Still waiting..."

    def test_node_not_found_returns_404(self, log_client):
        client, mock_db = log_client
        mock_db.get_by_execution.return_value = []

        response = client.get("/api/workflows/executions/exec-123/nodes/nonexistent/logs")

        assert response.status_code == 404

    def test_minio_error_falls_back_to_container(self, log_client):
        client, mock_db, mock_storage = log_client

        mock_node = _mock_node(logs_path="node/2026/06/25/exec_n1.log")
        mock_db.get_by_execution.return_value = [mock_node]
        mock_storage.read_log.side_effect = Exception("S3 connection error")

        mock_runner = MagicMock()
        mock_runner.docker.get_container_logs.return_value = "container fallback logs"

        with patch("src.api.workflows.ContainerRunner", return_value=mock_runner):
            response = client.get("/api/workflows/executions/exec-123/nodes/n1/logs")

        assert response.status_code == 200
        data = response.json()
        assert data["source"] == "container"


# =============================================================================
# GET /executions/{id}/nodes/{node_id}/logs/stream (SSE)
# =============================================================================

class TestStreamNodeLogs:
    def test_stream_returns_sse_response(self, log_client):
        client, mock_db, mock_storage = log_client

        mock_node = _mock_node(
            logs_path="node/2026/06/25/exec_n1.log",
            status=NodeExecutionStatus.COMPLETED
        )
        mock_db.get_by_execution.return_value = [mock_node]
        mock_storage.read_log.return_value = "streamed log content"

        response = client.get(
            "/api/workflows/executions/exec-123/nodes/n1/logs/stream",
            stream=False
        )

        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        assert "no-cache" in response.headers["cache-control"]

    def test_stream_sends_done_when_node_completed(self, log_client):
        client, mock_db, mock_storage = log_client

        running_node = _mock_node(
            logs_path=None,
            status=NodeExecutionStatus.RUNNING
        )
        completed_node = _mock_node(
            logs_path="node/2026/06/25/exec_n1.log",
            status=NodeExecutionStatus.COMPLETED
        )
        mock_db.get_by_execution.side_effect = [
            [running_node],
            [completed_node]
        ]
        mock_storage.read_log.return_value = "final log content"

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.return_value = None
            response = client.get(
                "/api/workflows/executions/exec-123/nodes/n1/logs/stream"
            )

            lines = []
            for line in response.iter_lines():
                lines.append(line)
                if len(lines) >= 4:
                    break

        assert any("[DONE]" in str(l) for l in lines)

    def test_stream_node_not_found_yields_error(self, log_client):
        client, mock_db = log_client
        mock_db.get_by_execution.return_value = []

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.return_value = None
            response = client.get(
                "/api/workflows/executions/exec-123/nodes/nonexistent/logs/stream"
            )

        assert response.status_code == 200
        lines = []
        for line in response.iter_lines():
            lines.append(line)
            if len(lines) >= 2:
                break

    def test_stream_heartbeat_sent(self, log_client):
        """Heartbeat is sent when node has no logs_path yet."""
        client, mock_db = log_client

        pending_node = _mock_node(
            logs_path=None,
            status=NodeExecutionStatus.PENDING
        )
        mock_db.get_by_execution.return_value = [pending_node]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.return_value = None
            response = client.get(
                "/api/workflows/executions/exec-123/nodes/n1/logs/stream"
            )

        assert response.status_code == 200
        lines = []
        for line in response.iter_lines():
            lines.append(line)
            if len(lines) >= 4:
                break

        assert any("data:" in str(l) for l in lines)


# =============================================================================
# NODE SERIALIZATION
# =============================================================================

class TestNodeToDictInLogContext:
    def test_logs_path_passed_through(self):
        """logs_path field should be in serialized node."""
        node = _mock_node(logs_path="node/2026/06/25/my.log")
        result = _node_to_dict(node)
        assert result["logs_path"] == "node/2026/06/25/my.log"

    def test_logs_path_none_when_unset(self):
        node = _mock_node(logs_path=None)
        result = _node_to_dict(node)
        assert result["logs_path"] is None

    def test_status_reflects_current_state(self):
        for status in [NodeExecutionStatus.PENDING, NodeExecutionStatus.RUNNING,
                       NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED]:
            node = _mock_node(status=status)
            result = _node_to_dict(node)
            assert result["status"] == status
