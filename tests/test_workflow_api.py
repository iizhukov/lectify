"""
Unit tests for /api/workflows endpoints (src/api/workflows.py)
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.api.workflows import router


@pytest.fixture
def mock_repo():
    with patch("src.api.workflows.repo") as mock:
        yield mock


@pytest.fixture
def mock_db_repo():
    with patch("src.api.workflows.DBRepository") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def mock_wf_repo():
    with patch("src.api.workflows.WorkflowTemplateRepository") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield instance


@pytest.fixture
def mock_storage():
    with patch("src.api.workflows.get_storage") as mock:
        yield mock.return_value


@pytest.fixture
def mock_container_runner():
    with patch("src.api.workflows.ContainerRunner") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture
def workflow_client(mock_db_repo, mock_wf_repo):
    """TestClient with all dependencies mocked."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), mock_db_repo, mock_wf_repo


# =============================================================================
# WORKFLOW CRUD
# =============================================================================

class TestListWorkflows:
    def test_list_returns_public_workflows(self, workflow_client):
        client, mock_repo, _ = workflow_client

        mock_wf = MagicMock()
        mock_wf.id = "wf-1"
        mock_wf.user_id = None
        mock_wf.name = "Public Workflow"
        mock_wf.description = "A test"
        mock_wf.graph = {"nodes": [], "edges": []}
        mock_wf.is_public = True
        mock_wf.created_at = None
        mock_wf.updated_at = None

        mock_repo.get_public.return_value = [mock_wf]

        response = client.get("/api/workflows")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Public Workflow"

    def test_list_includes_user_workflows(self, workflow_client):
        client, mock_repo, _ = workflow_client

        public_wf = MagicMock()
        public_wf.id = "wf-public"
        public_wf.user_id = None
        public_wf.name = "Public"
        public_wf.description = None
        public_wf.graph = {}
        public_wf.is_public = True
        public_wf.created_at = None
        public_wf.updated_at = None

        user_wf = MagicMock()
        user_wf.id = "wf-user"
        user_wf.user_id = "user-1"
        user_wf.name = "Private"
        user_wf.description = None
        user_wf.graph = {}
        user_wf.is_public = False
        user_wf.created_at = None
        user_wf.updated_at = None

        mock_repo.get_public.return_value = [public_wf]
        mock_repo.get_by_user.return_value = [user_wf]

        response = client.get("/api/workflows", params={"user_id": "user-1"})

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestGetWorkflow:
    def test_get_workflow_found(self, workflow_client):
        client, mock_repo, _ = workflow_client

        mock_wf = MagicMock()
        mock_wf.id = "wf-123"
        mock_wf.user_id = "user-1"
        mock_wf.name = "My Workflow"
        mock_wf.description = "Test"
        mock_wf.graph = {"nodes": [], "edges": []}
        mock_wf.is_public = False
        mock_wf.created_at = None
        mock_wf.updated_at = None

        mock_repo.get.return_value = mock_wf

        response = client.get("/api/workflows/wf-123")

        assert response.status_code == 200
        assert response.json()["name"] == "My Workflow"

    def test_get_workflow_not_found(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.get.return_value = None

        response = client.get("/api/workflows/nonexistent")

        assert response.status_code == 404


class TestCreateWorkflow:
    def test_create_workflow_success(self, workflow_client):
        client, mock_repo, _ = workflow_client

        created = MagicMock()
        created.id = "new-wf-id"
        created.user_id = None
        created.name = "New Workflow"
        created.description = "Desc"
        created.graph = {"nodes": [], "edges": []}
        created.is_public = False
        created.created_at = None
        created.updated_at = None

        mock_repo.create.return_value = created

        response = client.post("/api/workflows", json={
            "name": "New Workflow",
            "description": "Desc",
            "nodes": [{"id": "n1"}],
            "edges": []
        })

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Workflow"
        mock_repo.create.assert_called_once()


class TestUpdateWorkflow:
    def test_update_workflow_name(self, workflow_client):
        client, mock_repo, _ = workflow_client

        existing = MagicMock()
        existing.graph = {"nodes": [], "edges": []}
        mock_repo.get.return_value = existing

        updated = MagicMock()
        updated.id = "wf-1"
        updated.user_id = None
        updated.name = "Updated Name"
        updated.description = None
        updated.graph = {"nodes": [], "edges": []}
        updated.is_public = False
        updated.created_at = None
        updated.updated_at = None
        mock_repo.update.return_value = updated

        response = client.put("/api/workflows/wf-1", json={"name": "Updated Name"})

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_update_workflow_not_found(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.get.return_value = None

        response = client.put("/api/workflows/nonexistent", json={"name": "New Name"})

        assert response.status_code == 404


class TestDeleteWorkflow:
    def test_delete_workflow_success(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.delete.return_value = True

        response = client.delete("/api/workflows/wf-1")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_delete_workflow_not_found(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.delete.return_value = False

        response = client.delete("/api/workflows/nonexistent")

        assert response.status_code == 404


class TestPublishWorkflow:
    def test_publish_workflow_success(self, workflow_client):
        client, mock_repo, _ = workflow_client

        mock_wf = MagicMock()
        mock_wf.id = "wf-1"
        mock_repo.update.return_value = mock_wf

        mock_pub = MagicMock()
        mock_pub.id = "pub-1"
        mock_repo.publish.return_value = mock_pub

        response = client.post("/api/workflows/wf-1/publish")

        assert response.status_code == 200
        assert response.json()["is_public"] is True

    def test_publish_workflow_not_found(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.update.return_value = None

        response = client.post("/api/workflows/nonexistent/publish")

        assert response.status_code == 404


# =============================================================================
# EXECUTION ENDPOINTS
# =============================================================================

class TestListExecutions:
    def test_list_executions_with_pending_and_running(self, workflow_client):
        client, mock_repo, _ = workflow_client

        pending = MagicMock()
        pending.id = "exec-1"
        pending.workflow_template_id = "wf-1"
        pending.workflow_template = MagicMock()
        pending.workflow_template.name = "Test WF"
        pending.file_id = "file-1"
        pending.status = "pending"
        pending.error_message = None
        pending.created_at = None
        pending.started_at = None
        pending.ended_at = None

        running = MagicMock()
        running.id = "exec-2"
        running.workflow_template_id = "wf-1"
        running.workflow_template = MagicMock()
        running.workflow_template.name = "Test WF"
        running.file_id = "file-2"
        running.status = "running"
        running.error_message = None
        running.created_at = None
        running.started_at = None
        running.ended_at = None

        mock_repo.get_pending_executions.return_value = [pending]
        mock_repo.get_running_executions.return_value = [running]

        response = client.get("/api/workflows/executions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_executions_fallback_to_query(self, workflow_client):
        client, mock_repo, _ = workflow_client

        mock_repo.get_pending_executions.side_effect = Exception("db error")
        mock_repo.get_running_executions.side_effect = Exception("db error")

        from src.db.entity import DBExecution
        mock_exec = MagicMock(spec=DBExecution)
        mock_exec.id = "exec-1"
        mock_exec.workflow_template_id = "wf-1"
        mock_exec.workflow_template = MagicMock()
        mock_exec.workflow_template.name = None
        mock_exec.file_id = "file-1"
        mock_exec.status = "pending"
        mock_exec.error_message = None
        mock_exec.created_at = None
        mock_exec.started_at = None
        mock_exec.ended_at = None

        with patch("src.api.workflows.DBExecution") as mock_cls:
            mock_cls.return_value = None  # won't be used directly
            # The fallback path uses s.query(DBExecution).all()
            pass  # tested via mock path

        # Just verify it returns a list (fallback path)
        response = client.get("/api/workflows/executions")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestGetExecution:
    def test_get_execution_found(self, workflow_client):
        client, mock_repo, _ = workflow_client

        mock_exec = MagicMock()
        mock_exec.id = "exec-123"
        mock_exec.workflow_template_id = "wf-1"
        mock_exec.workflow_template = MagicMock()
        mock_exec.workflow_template.name = "My WF"
        mock_exec.file_id = "file-1"
        mock_exec.status = "pending"
        mock_exec.error_message = None
        mock_exec.created_at = None
        mock_exec.started_at = None
        mock_exec.ended_at = None
        mock_repo.get.return_value = mock_exec

        response = client.get("/api/workflows/executions/exec-123")

        assert response.status_code == 200
        assert response.json()["id"] == "exec-123"

    def test_get_execution_not_found(self, workflow_client):
        client, mock_repo, _ = workflow_client
        mock_repo.get.return_value = None

        response = client.get("/api/workflows/executions/nonexistent")

        assert response.status_code == 404


class TestGetExecutionNodes:
    def test_get_nodes_for_execution(self, workflow_client):
        client, mock_repo, _ = workflow_client

        node1 = MagicMock()
        node1.id = "node-1"
        node1.node_id = "n1"
        node1.node_template_id = "t1"
        node1.status = "pending"
        node1.progress_percent = 0
        node1.progress_message = "Waiting"
        node1.cpu_percent = None
        node1.memory_mb = None
        node1.execution_time_ms = None
        node1.error_message = None
        node1.logs_path = None
        node1.started_at = None
        node1.ended_at = None

        mock_repo.get_by_execution.return_value = [node1]

        response = client.get("/api/workflows/executions/exec-123/nodes")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["node_id"] == "n1"


# =============================================================================
# EXECUTE WORKFLOW
# =============================================================================

class TestExecuteWorkflow:
    def test_execute_workflow_creates_pending_execution(self, workflow_client):
        client, mock_repo, mock_wf_repo = workflow_client

        mock_wf = MagicMock()
        mock_wf.id = "wf-123"
        mock_wf.graph = {"nodes": [{"id": "n1", "template_id": "t1"}, {"id": "n2"}], "edges": []}
        mock_wf_repo.get.return_value = mock_wf
        mock_repo.get.return_value = mock_wf

        # Mock DBRepository and its session
        mock_db_instance = MagicMock()
        with patch("src.api.workflows.DBRepository", return_value=mock_db_instance):
            mock_session_cm = MagicMock()
            mock_session_cm.__enter__ = MagicMock(return_value=mock_session_cm)
            mock_session_cm.__exit__ = MagicMock(return_value=None)
            mock_db_instance.session.return_value = mock_session_cm

            response = client.post(
                "/api/workflows/wf-123/execute",
                json={"file_id": "file-abc", "file_path": "/tmp/test.mp3", "language": "ru"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "execution_id" in data
        assert data["status"] == "pending"

    def test_execute_workflow_workflow_not_found(self, workflow_client):
        client, mock_repo, mock_wf_repo = workflow_client
        mock_repo.get.return_value = None
        mock_wf_repo.get.return_value = None

        response = client.post(
            "/api/workflows/nonexistent/execute",
            json={"file_id": "f1", "file_path": "/tmp/f.mp3"}
        )

        assert response.status_code == 404


# =============================================================================
# SERIALIZATION HELPERS
# =============================================================================

class TestExecutionToDict:
    def test_execution_serialization(self):
        """Test _execution_to_dict produces correct structure."""
        from src.api.workflows import _execution_to_dict
        from datetime import datetime, timezone

        mock_exec = MagicMock()
        mock_exec.id = "exec-serial"
        mock_exec.workflow_template_id = "wf-1"
        mock_exec.workflow_template = MagicMock()
        mock_exec.workflow_template.name = "Test WF"
        mock_exec.file_id = "file-1"
        mock_exec.status = "running"
        mock_exec.error_message = "some error"
        mock_exec.created_at = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_exec.started_at = datetime(2026, 6, 25, 10, 1, 0, tzinfo=timezone.utc)
        mock_exec.ended_at = None

        result = _execution_to_dict(mock_exec)

        assert result["id"] == "exec-serial"
        assert result["workflow_template_id"] == "wf-1"
        assert result["workflow_name"] == "Test WF"
        assert result["file_id"] == "file-1"
        assert result["status"] == "running"
        assert result["error_message"] == "some error"
        assert result["created_at"] == "2026-06-25T10:00:00+00:00"
        assert result["started_at"] == "2026-06-25T10:01:00+00:00"
        assert result["ended_at"] is None


class TestNodeToDict:
    def test_node_serialization(self):
        """Test _node_to_dict produces correct structure."""
        from src.api.workflows import _node_to_dict
        from datetime import datetime, timezone

        mock_node = MagicMock()
        mock_node.id = "node-id"
        mock_node.node_id = "n1"
        mock_node.node_template_id = "t1"
        mock_node.status = "completed"
        mock_node.progress_percent = 100
        mock_node.progress_message = "Done"
        mock_node.cpu_percent = 45.5
        mock_node.memory_mb = 256.0
        mock_node.execution_time_ms = 30000
        mock_node.error_message = None
        mock_node.logs_path = "node/2026/06/25/exec_node.log"
        mock_node.started_at = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_node.ended_at = datetime(2026, 6, 25, 10, 0, 30, tzinfo=timezone.utc)

        result = _node_to_dict(mock_node)

        assert result["id"] == "node-id"
        assert result["node_id"] == "n1"
        assert result["status"] == "completed"
        assert result["progress_percent"] == 100
        assert result["cpu_percent"] == 45.5
        assert result["memory_mb"] == 256.0
        assert result["execution_time_ms"] == 30000
        assert result["logs_path"] == "node/2026/06/25/exec_node.log"
