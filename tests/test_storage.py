"""
Интеграционные тесты для MinIO хранилища
"""
import pytest
import uuid
from pathlib import Path

from src.utils.storage import MinIOStorage


@pytest.mark.integration
@pytest.mark.storage
class TestMinIOStorage:
    """Тесты работы с MinIO хранилищем"""
    
    def test_upload_artifact(self, test_storage, sample_text_file):
        """Тест загрузки артефакта"""
        workflow_id = str(uuid.uuid4())
        node_id = "test_node"
        
        minio_path = test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id=node_id,
            artifact_type="text"
        )
        
        assert minio_path is not None
        assert workflow_id in minio_path
        assert node_id in minio_path
        assert "text" in minio_path
    
    def test_download_artifact(self, test_storage, sample_text_file, temp_dir):
        """Тест скачивания артефакта"""
        workflow_id = str(uuid.uuid4())
        node_id = "test_node"
        
        # Загружаем
        minio_path = test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id=node_id,
            artifact_type="text"
        )
        
        # Скачиваем
        download_path = temp_dir / "downloaded.txt"
        success = test_storage.download_artifact(
            object_name=minio_path,
            destination_path=str(download_path)
        )
        
        assert success is True
        assert download_path.exists()
        assert download_path.read_text() == sample_text_file.read_text()
    
    def test_get_artifact_url(self, test_storage, sample_text_file):
        """Тест получения presigned URL"""
        workflow_id = str(uuid.uuid4())
        node_id = "test_node"
        
        minio_path = test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id=node_id,
            artifact_type="text"
        )
        
        url = test_storage.get_artifact_url(minio_path, expires_hours=1)
        
        assert url is not None
        assert "localhost:9000" in url
        assert minio_path in url
    
    def test_list_workflow_artifacts(self, test_storage, sample_text_file, sample_markdown_file):
        """Тест получения списка артефактов воркфлоу"""
        workflow_id = str(uuid.uuid4())
        
        # Загружаем несколько артефактов
        test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id="node1",
            artifact_type="text"
        )
        
        test_storage.upload_artifact(
            file_path=str(sample_markdown_file),
            workflow_id=workflow_id,
            node_id="node2",
            artifact_type="markdown"
        )
        
        # Получаем список
        artifacts = test_storage.list_workflow_artifacts(workflow_id)
        
        assert len(artifacts) == 2
        assert all(workflow_id in a["object_name"] for a in artifacts)
    
    def test_delete_workflow_artifacts(self, test_storage, sample_text_file):
        """Тест удаления всех артефактов воркфлоу"""
        workflow_id = str(uuid.uuid4())
        
        # Загружаем артефакт
        test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id="test_node",
            artifact_type="text"
        )
        
        # Проверяем, что есть
        artifacts_before = test_storage.list_workflow_artifacts(workflow_id)
        assert len(artifacts_before) > 0
        
        # Удаляем
        success = test_storage.delete_workflow_artifacts(workflow_id)
        assert success is True
        
        # Проверяем, что удалены
        artifacts_after = test_storage.list_workflow_artifacts(workflow_id)
        assert len(artifacts_after) == 0
    
    def test_upload_log(self, test_storage, sample_text_file):
        """Тест загрузки лог-файла"""
        minio_path = test_storage.upload_log(
            log_file_path=str(sample_text_file),
            log_type="application"
        )
        
        assert minio_path is not None
        assert "application" in minio_path
    
    def test_content_type_detection(self, test_storage):
        """Тест определения content type"""
        test_cases = [
            ("/path/to/file.mp3", "audio/mpeg"),
            ("/path/to/file.mp4", "video/mp4"),
            ("/path/to/file.txt", "text/plain"),
            ("/path/to/file.md", "text/markdown"),
            ("/path/to/file.pdf", "application/pdf"),
            ("/path/to/file.unknown", "application/octet-stream")
        ]
        
        for file_path, expected_type in test_cases:
            content_type = test_storage._get_content_type(file_path)
            assert content_type == expected_type
    
    def test_upload_nonexistent_file(self, test_storage):
        """Тест загрузки несуществующего файла"""
        minio_path = test_storage.upload_artifact(
            file_path="/nonexistent/file.txt",
            workflow_id="test",
            node_id="test",
            artifact_type="text"
        )
        
        assert minio_path is None
    
    def test_download_nonexistent_artifact(self, test_storage, temp_dir):
        """Тест скачивания несуществующего артефакта"""
        download_path = temp_dir / "nonexistent.txt"
        success = test_storage.download_artifact(
            object_name="nonexistent/path/file.txt",
            destination_path=str(download_path)
        )
        
        assert success is False
        assert not download_path.exists()
    
    def test_artifact_structure(self, test_storage, sample_text_file):
        """Тест структуры хранения артефактов"""
        workflow_id = "550e8400-e29b-41d4-a716-446655440000"
        node_id = "speech_to_text"
        artifact_type = "text"
        
        minio_path = test_storage.upload_artifact(
            file_path=str(sample_text_file),
            workflow_id=workflow_id,
            node_id=node_id,
            artifact_type=artifact_type
        )
        
        # Проверяем структуру: {workflow_id}/{node_id}/{artifact_type}/{filename}
        parts = minio_path.split("/")
        assert parts[0] == workflow_id
        assert parts[1] == node_id
        assert parts[2] == artifact_type
        assert parts[3] == sample_text_file.name
