import pytest


@pytest.mark.integration
@pytest.mark.api
class TestWorkflowsAPIV2:
    """Тесты для нового Workflow API (/api/workflows)"""

    def test_list_workflows_empty(self, client):
        """Должен вернуть пустой список когда нет воркфлоу"""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_workflow(self, client):
        """Должен создать новый воркфлоу"""
        workflow_data = {
            "name": "Test Workflow",
            "description": "A test workflow",
            "graph": {
                "nodes": [
                    {"id": "node_1", "plugin_id": "media_converter", "name": "Convert"}
                ],
                "edges": []
            }
        }

        response = client.post("/api/workflows", json=workflow_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Workflow"
        assert "id" in data

    def test_get_workflow_not_found(self, client):
        """Должен вернуть 404 для несуществующего воркфлоу"""
        response = client.get("/api/workflows/nonexistent-id")
        assert response.status_code == 404

    def test_update_workflow(self, client):
        """Должен обновить воркфлоу"""
        # Создаём воркфлоу
        create_response = client.post("/api/workflows", json={
            "name": "Original Name",
            "graph": {"nodes": [], "edges": []}
        })
        workflow_id = create_response.json()["id"]

        # Обновляем
        response = client.put(f"/api/workflows/{workflow_id}", json={
            "name": "Updated Name"
        })

        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"

    def test_delete_workflow(self, client):
        """Должен удалить воркфлоу"""
        create_response = client.post("/api/workflows", json={
            "name": "To Delete",
            "graph": {"nodes": [], "edges": []}
        })
        workflow_id = create_response.json()["id"]

        response = client.delete(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200

        # Проверяем что удалён
        get_response = client.get(f"/api/workflows/{workflow_id}")
        assert get_response.status_code == 404


@pytest.mark.integration
@pytest.mark.api
class TestNodesAPIV2:
    """Тесты для Nodes API (/api/nodes)"""

    def test_list_nodes(self, client):
        """Должен вернуть список нод"""
        response = client.get("/api/nodes")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_list_plugins(self, client):
        """Должен вернуть список плагинов"""
        response = client.get("/api/nodes/plugins")
        assert response.status_code == 200
        plugins = response.json()
        assert len(plugins) > 0
        assert all("id" in p for p in plugins)
        assert all("name" in p for p in plugins)

    def test_get_plugin_details(self, client):
        """Должен вернуть детали плагина со схемой"""
        response = client.get("/api/nodes/plugins/media_converter")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "media_converter"
        assert "schema" in data

    def test_get_plugin_not_found(self, client):
        """Должен вернуть 404 для несуществующего плагина"""
        response = client.get("/api/nodes/plugins/nonexistent-plugin")
        assert response.status_code == 404

    def test_create_node(self, client, test_user, test_plugin):
        """Должен создать новую ноду"""
        # Проверяем что плагин зарегистрирован
        response = client.get("/api/nodes/plugins/media_converter")
        assert response.status_code == 200

        node_data = {
            "plugin_id": "media_converter",
            "name": "Test Node",
            "description": "A test node",
            "parameters": {"format": "m4a", "bitrate": "64k"}
        }

        # Создаём ноду от имени пользователя
        response = client.post("/api/nodes", json=node_data, params={"user_id": test_user.id})
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Node"
        assert data["plugin_id"] == "media_converter"

    def test_create_node_invalid_plugin(self, client):
        """Должен вернуть 400 для невалидного плагина"""
        node_data = {
            "plugin_id": "nonexistent-plugin",
            "name": "Invalid Node"
        }

        response = client.post("/api/nodes", json=node_data)
        assert response.status_code == 400


@pytest.mark.integration
@pytest.mark.api
class TestPromptsAPIV2:
    """Тесты для Prompts API (/api/prompts)"""

    def test_list_prompts(self, client):
        """Должен вернуть список промптов"""
        response = client.get("/api/prompts")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_prompt(self, client):
        """Должен создать новый промпт"""
        prompt_data = {
            "name": "Test Prompt",
            "system_prompt": "You are a helpful assistant.",
            "user_prompt_template": "Summarize: {{text}}",
            "variables": ["text"]
        }

        response = client.post("/api/prompts", json=prompt_data)
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Prompt"
        assert "id" in data

    def test_get_prompt(self, client):
        """Должен получить промпт по ID"""
        create_response = client.post("/api/prompts", json={
            "name": "Test Prompt",
            "user_prompt_template": "Hello {{name}}!"
        })
        prompt_id = create_response.json()["id"]

        response = client.get(f"/api/prompts/{prompt_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test Prompt"

    def test_render_prompt(self, client):
        """Должен рендерить промпт с переменными"""
        create_response = client.post("/api/prompts", json={
            "name": "Greeting",
            "system_prompt": "You are friendly.",
            "user_prompt_template": "Hello {{name}}!"
        })
        prompt_id = create_response.json()["id"]

        response = client.get(f"/api/prompts/{prompt_id}/render", params={"name": "name", "value": "World"})
        assert response.status_code == 200
        data = response.json()
        assert "World" in data["user_prompt"]
