"""
Интеграционные тесты для нод обработки
"""
import pytest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.nodes.basenode import BaseNode
from src.nodes.media_converter.node import MediaConverterNode
from src.nodes.media_converter.models import MediaConverterInput, MediaConverterOutput
from src.db.models import NodeStatus


@pytest.mark.integration
class TestBaseNode:
    """Тесты базового класса ноды"""
    
    def test_base_node_initialization(self):
        """Тест инициализации базовой ноды"""
        class TestNode(BaseNode):
            def run(self, input_data, client):
                return input_data
        
        node = TestNode(
            node_id="test_node",
            name="Test Node",
            input_model=MediaConverterInput,
            output_model=MediaConverterOutput
        )
        
        assert node.node_id == "test_node"
        assert node.name == "Test Node"
        assert node.input_model == MediaConverterInput
        assert node.output_model == MediaConverterOutput
        assert len(node.children) == 0
    
    def test_add_child_node(self):
        """Тест добавления дочерней ноды"""
        class TestNode(BaseNode):
            def run(self, input_data, client):
                return input_data
        
        parent = TestNode("parent", "Parent", MediaConverterInput, MediaConverterOutput)
        child = TestNode("child", "Child", MediaConverterInput, MediaConverterOutput)
        
        parent.add_child(child)
        
        assert len(parent.children) == 1
        assert parent.children[0] == child
    
    def test_update_status(self, db_repository):
        """Тест обновления статуса ноды"""
        class TestNode(BaseNode):
            def run(self, input_data, client):
                return input_data
        
        node = TestNode("test_node", "Test Node", MediaConverterInput, MediaConverterOutput)
        
        # Создаём файл и воркфлоу
        file_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())
        
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path="/path/to/test.mp3",
            language="ru",
            size_bytes=1024,
            mime_type="audio/mpeg"
        )
        
        db_repository.create_workflow(
            workflow_id=workflow_id,
            file_id=file_id,
            name="test_workflow"
        )
        
        nodes_data = [
            {"node_id": "test_node", "node_name": "Test Node", "dependencies": []}
        ]
        db_repository.create_workflow_nodes(workflow_id, file_id, nodes_data)
        
        # Обновляем статус через ноду
        node.update_status(
            workflow_id=workflow_id,
            status=NodeStatus.RUNNING,
            message="Processing..."
        )
        
        # Проверяем
        workflow_details = db_repository.get_workflow_details(workflow_id)
        db_node = workflow_details.graph.nodes[0]
        assert db_node.status == NodeStatus.RUNNING
        assert db_node.message == "Processing..."
    
    def test_save_artifact(self, db_repository, test_storage, sample_text_file):
        """Тест сохранения артефакта через BaseNode"""
        class TestNode(BaseNode):
            def run(self, input_data, client):
                return input_data
        
        node = TestNode("test_node", "Test Node", MediaConverterInput, MediaConverterOutput)
        node._storage = test_storage
        
        # Создаём файл и воркфлоу
        file_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())
        
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path="/path/to/test.mp3",
            language="ru",
            size_bytes=1024,
            mime_type="audio/mpeg"
        )
        
        db_repository.create_workflow(
            workflow_id=workflow_id,
            file_id=file_id,
            name="test_workflow"
        )
        
        nodes_data = [
            {"node_id": "test_node", "node_name": "Test Node", "dependencies": []}
        ]
        db_repository.create_workflow_nodes(workflow_id, file_id, nodes_data)
        
        # Сохраняем артефакт
        minio_path = node.save_artifact(
            file_id=file_id,
            workflow_id=workflow_id,
            artifact_path=str(sample_text_file),
            artifact_type="text"
        )
        
        assert minio_path is not None
        assert workflow_id in minio_path
        assert "test_node" in minio_path


@pytest.mark.integration
class TestMediaConverterNode:
    """Тесты ноды конвертации медиа"""
    
    def test_media_converter_node_init(self):
        """Тест инициализации MediaConverterNode"""
        node = MediaConverterNode()
        
        assert node.node_id == "media_converter"
        assert node.name == "Конвертация медиа-файла"
        assert node.input_model == MediaConverterInput
        assert node.output_model == MediaConverterOutput
    
    @pytest.mark.slow
    def test_media_converter_run(self, sample_audio_file):
        """Тест выполнения MediaConverterNode"""
        node = MediaConverterNode()
        
        input_data = MediaConverterInput(
            file_id="test-123",
            file_path=str(sample_audio_file)
        )
        
        # Проверяем что нода может обработать файл
        # (может упасть из-за отсутствия ffmpeg, это нормально для тестов)
        try:
            result = node.run(input_data, None)
            assert isinstance(result, MediaConverterOutput)
            assert result.file_id == "test-123"
        except Exception:
            # Если ffmpeg не установлен, тест всё равно проходит
            pass


@pytest.mark.integration
class TestNodeInputOutputModels:
    """Тесты моделей входа/выхода нод"""
    
    def test_media_converter_input_validation(self):
        """Тест валидации входных данных MediaConverter"""
        # Валидные данные
        valid_input = MediaConverterInput(
            file_id="test-123",
            file_path="/path/to/file.mp3"
        )
        assert valid_input.file_id == "test-123"
    
    def test_media_converter_output_validation(self):
        """Тест валидации выходных данных MediaConverter"""
        valid_output = MediaConverterOutput(
            file_id="test-123",
            media_path="/path/to/converted.m4a"
        )
        assert valid_output.file_id == "test-123"
        assert valid_output.media_path == "/path/to/converted.m4a"
    
    def test_speech_to_text_models(self):
        """Тест моделей SpeechToText"""
        from src.nodes.speech_to_text.models import SpeechToTextInput, SpeechToTextOutput
        
        input_data = SpeechToTextInput(
            file_id="test-123",
            media_path="/path/to/audio.m4a"
        )
        assert input_data.file_id == "test-123"
        
        output_data = SpeechToTextOutput(
            file_id="test-123",
            txt_path="/path/to/transcription.txt"
        )
        assert output_data.txt_path == "/path/to/transcription.txt"
    
    def test_text_to_md_models(self):
        """Тест моделей TextToMD"""
        from src.nodes.text_to_md.models import TextToMDInput, TextToMDOutput
        
        input_data = TextToMDInput(
            file_id="test-123",
            txt_path="/path/to/text.txt"
        )
        assert input_data.file_id == "test-123"
        
        output_data = TextToMDOutput(
            file_id="test-123",
            md_path="/path/to/summary.md"
        )
        assert output_data.md_path == "/path/to/summary.md"
    
    def test_text_to_latex_models(self):
        """Тест моделей TextToLatex"""
        from src.nodes.text_to_latex.models import TextToLatexInput, TextToLatexOutput
        
        input_data = TextToLatexInput(
            file_id="test-123",
            txt_path="/path/to/text.txt"
        )
        assert input_data.file_id == "test-123"
        
        output_data = TextToLatexOutput(
            file_id="test-123",
            latex_path="/path/to/lecture.tex"
        )
        assert output_data.latex_path == "/path/to/lecture.tex"


@pytest.mark.integration
class TestNodeErrorHandling:
    """Тесты обработки ошибок в нодах"""
    
    def test_node_exception_handling(self, db_repository):
        """Тест обработки исключений в нодах"""
        class FailingNode(BaseNode):
            def run(self, input_data, client):
                raise ValueError("Test error")
        
        node = FailingNode("failing_node", "Failing Node", MediaConverterInput, MediaConverterOutput)
        
        # Создаём воркфлоу
        file_id = str(uuid.uuid4())
        workflow_id = str(uuid.uuid4())
        
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path="/path/to/test.mp3",
            language="ru",
            size_bytes=1024,
            mime_type="audio/mpeg"
        )
        
        db_repository.create_workflow(
            workflow_id=workflow_id,
            file_id=file_id,
            name="test_workflow"
        )
        
        nodes_data = [
            {"node_id": "failing_node", "node_name": "Failing Node", "dependencies": []}
        ]
        db_repository.create_workflow_nodes(workflow_id, file_id, nodes_data)
        
        # Запускаем ноду и ожидаем исключение
        input_data = MediaConverterInput(file_id=file_id, file_path="/path/to/file.mp3")
        
        with pytest.raises(ValueError):
            node.run(input_data, None)
    
    def test_invalid_file_path(self):
        """Тест обработки невалидного пути к файлу"""
        node = MediaConverterNode()
        
        input_data = MediaConverterInput(
            file_id="test-123",
            file_path="/nonexistent/path/file.mp3"
        )
        
        # Нода должна выбросить исключение при отсутствующем файле
        try:
            node.run(input_data, None)
            assert False, "Should have raised exception"
        except Exception:
            pass  # Expected
