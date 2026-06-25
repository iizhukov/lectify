"""
Интеграционные тесты для API endpoints
"""
import pytest


@pytest.mark.integration
@pytest.mark.api
class TestAPIEndpoints:
    """Тесты API endpoints"""
    
    def test_root_endpoint(self, client):
        """Тест корневого endpoint"""
        response = client.get("/")
        assert response.status_code == 200
    
    def test_upload_file(self, client, sample_audio_file):
        """Тест загрузки файла"""
        with open(sample_audio_file, "rb") as f:
            response = client.post(
                "/upload",
                files={"file": ("test.mp3", f, "audio/mpeg")},
                data={"language": "ru"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert "workflow_id" in data
    
    def test_upload_invalid_file_type(self, client, temp_dir):
        """Тест загрузки файла неподдерживаемого типа"""
        invalid_file = temp_dir / "test.exe"
        invalid_file.write_bytes(b"fake executable")
        
        with open(invalid_file, "rb") as f:
            response = client.post(
                "/upload",
                files={"file": ("test.exe", f, "application/octet-stream")},
                data={"language": "ru"}
            )
        
        assert response.status_code == 400
    
    def test_get_files_list(self, client):
        """Тест получения списка файлов"""
        response = client.get("/api/files")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_file_details(self, client, sample_audio_file):
        """Тест получения деталей файла"""
        # Сначала загружаем файл
        with open(sample_audio_file, "rb") as f:
            upload_response = client.post(
                "/upload",
                files={"file": ("test.mp3", f, "audio/mpeg")},
                data={"language": "ru"}
            )
        
        file_id = upload_response.json()["file_id"]
        
        # Получаем детали
        response = client.get(f"/api/files/{file_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == file_id
        assert "workflows" in data
    
    def test_get_nonexistent_file(self, client):
        """Тест получения несуществующего файла"""
        response = client.get("/api/files/nonexistent-id")
        assert response.status_code == 404
    
    def test_get_workflow_details(self, client, sample_audio_file):
        """Тест получения деталей воркфлоу"""
        # Загружаем файл (создаётся воркфлоу)
        with open(sample_audio_file, "rb") as f:
            upload_response = client.post(
                "/upload",
                files={"file": ("test.mp3", f, "audio/mpeg")},
                data={"language": "ru"}
            )
        
        file_id = upload_response.json()["file_id"]
        
        # Получаем детали воркфлоу (workflow_id == file_id)
        response = client.get(f"/api/workflows/history/{file_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == file_id
        assert "graph" in data
    
    def test_metrics_endpoint(self, client):
        """Тест endpoint метрик Prometheus"""
        response = client.get("/metrics")
        assert response.status_code == 200
        # Проверяем что возвращается текст (метрики Prometheus)
        assert len(response.text) > 0
    
    def test_alert_webhook(self, client):
        """Тест webhook для алертов"""
        alert_data = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "TestAlert",
                        "severity": "warning"
                    },
                    "annotations": {
                        "summary": "Test alert summary",
                        "description": "Test alert description"
                    }
                }
            ]
        }
        
        response = client.post("/api/alerts/webhook", json=alert_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["received"] == 1
    
    def test_file_details_page(self, client, sample_audio_file):
        """Тест страницы деталей файла"""
        # Загружаем файл
        with open(sample_audio_file, "rb") as f:
            upload_response = client.post(
                "/upload",
                files={"file": ("test.mp3", f, "audio/mpeg")},
                data={"language": "ru"}
            )
        
        file_id = upload_response.json()["file_id"]
        
        # Получаем страницу
        response = client.get(f"/files/{file_id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
    
    def test_concurrent_uploads(self, client, sample_audio_file):
        """Тест одновременной загрузки нескольких файлов"""
        responses = []
        
        for i in range(3):
            with open(sample_audio_file, "rb") as f:
                response = client.post(
                    "/upload",
                    files={"file": (f"test_{i}.mp3", f, "audio/mpeg")},
                    data={"language": "ru"}
                )
                responses.append(response)
        
        # Все загрузки должны быть успешными
        assert all(r.status_code == 200 for r in responses)
        
        # Все file_id должны быть уникальными
        file_ids = [r.json()["file_id"] for r in responses]
        assert len(file_ids) == len(set(file_ids))
    
    def test_upload_without_file(self, client):
        """Тест загрузки без файла"""
        response = client.post(
            "/upload",
            data={"language": "ru"}
        )
        assert response.status_code == 422  # Validation error
    
    def test_upload_large_file_name(self, client, sample_audio_file):
        """Тест загрузки файла с очень длинным именем"""
        long_name = "a" * 200 + ".mp3"

        with open(sample_audio_file, "rb") as f:
            response = client.post(
                "/upload",
                files={"file": (long_name, f, "audio/mpeg")},
                data={"language": "ru"}
            )

        assert response.status_code == 200


# =============================================
# NEW WORKFLOW API TESTS
# =============================================

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
            "nodes": [
                {"id": "node_1", "template_id": "t1", "position_x": 0, "position_y": 0}
            ],
            "edges": []
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
            "nodes": [],
            "edges": []
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
            "nodes": [],
            "edges": []
        })
        workflow_id = create_response.json()["id"]

        response = client.delete(f"/api/workflows/{workflow_id}")
        assert response.status_code == 200

        # Проверяем что удалён
        get_response = client.get(f"/api/workflows/{workflow_id}")
        assert get_response.status_code == 404

    def test_publish_workflow(self, client):
        """Должен опубликовать воркфлоу"""
        create_response = client.post("/api/workflows", json={
            "name": "Public Workflow",
            "nodes": [],
            "edges": []
        })
        workflow_id = create_response.json()["id"]

        response = client.post(f"/api/workflows/{workflow_id}/publish")
        assert response.status_code == 200
        assert response.json()["is_public"] is True

    def test_fork_workflow(self, client, test_user):
        """Должен сделать fork воркфлоу"""
        # Создаём воркфлоу
        create_response = client.post("/api/workflows", json={
            "name": "Fork Source",
            "nodes": [
                {"id": "n1", "template_id": "t1"}
            ],
            "edges": []
        })
        workflow_id = create_response.json()["id"]

        # Публикуем воркфлоу
        publish_response = client.post(f"/api/workflows/{workflow_id}/publish")
        assert publish_response.status_code == 200

        # Fork с указанием user_id (используем оригинальный workflow_id)
        response = client.post(f"/api/workflows/public/{workflow_id}/fork", params={"user_id": test_user.id})

        assert response.status_code == 200
        data = response.json()
        assert data["workflow_id"] is not None


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
