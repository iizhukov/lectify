"""
Интеграционные тесты для воркфлоу и оркестратора
"""
import pytest
import uuid
import time
from unittest.mock import MagicMock, patch

from src.workflows.workflow import Workflow
from src.workflows.registry import create_lecture_workflow
from src.workflows.orchestrator import LectureOrchestrator
from src.workflows.converter import get_converter
from src.nodes.media_converter.models import MediaConverterInput, MediaConverterOutput
from src.nodes.speech_to_text.models import SpeechToTextInput, SpeechToTextOutput


@pytest.mark.integration
@pytest.mark.workflow
class TestWorkflow:
    """Тесты структуры воркфлоу"""
    
    def test_create_lecture_workflow(self):
        """Тест создания воркфлоу лекции"""
        workflow = create_lecture_workflow()
        
        assert workflow is not None
        assert workflow.name == "Lecture Conspectus Workflow"
        assert workflow.root_node is not None
        assert workflow.root_node.node_id == "media_converter"
    
    def test_workflow_nodes_structure(self):
        """Тест структуры нод воркфлоу"""
        workflow = create_lecture_workflow()
        
        # Собираем все ноды
        all_nodes = workflow.all_nodes
        
        # Проверяем наличие всех нод
        node_ids = [node.node_id for node in all_nodes]
        expected_nodes = [
            "media_converter",
            "speech_to_text",
            "text_to_md",
            "text_to_latex",
            "latex_to_pdf"
        ]
        
        for expected in expected_nodes:
            assert expected in node_ids
    
    def test_workflow_dependencies(self):
        """Тест зависимостей между нодами"""
        workflow = create_lecture_workflow()
        
        # media_converter -> speech_to_text
        assert len(workflow.root_node.children) > 0
        
        # speech_to_text -> text_to_md и text_to_latex
        s2t_node = next(n for n in workflow.root_node.children if n.node_id == "speech_to_text")
        assert len(s2t_node.children) >= 2
        
        # text_to_latex -> latex_to_pdf
        latex_node = next(n for n in s2t_node.children if n.node_id == "text_to_latex")
        assert len(latex_node.children) > 0
    
    def test_workflow_converters(self):
        """Тест конвертеров между нодами"""
        # MediaConverterOutput -> SpeechToTextInput
        converter = get_converter(MediaConverterOutput, SpeechToTextInput)
        assert converter is not None
        
        output = MediaConverterOutput(file_id="test", media_path="/path/to/file.m4a")
        converted = converter(output)
        
        assert isinstance(converted, SpeechToTextInput)
        assert converted.file_id == "test"
        assert converted.media_path == "/path/to/file.m4a"


@pytest.mark.integration
@pytest.mark.workflow
class TestOrchestrator:
    """Тесты оркестратора воркфлоу"""
    
    def test_orchestrator_singleton(self, mock_llm_client):
        """Тест паттерна Singleton для оркестратора"""
        orchestrator1 = LectureOrchestrator(mock_llm_client)
        orchestrator2 = LectureOrchestrator()
        
        assert orchestrator1 is orchestrator2
    
    def test_init_workflow(self, mock_llm_client, db_repository):
        """Тест инициализации воркфлоу"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        file_id = str(uuid.uuid4())
        
        # Создаём файл
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path="/path/to/test.mp3",
            language="ru",
            size_bytes=1024,
            mime_type="audio/mpeg"
        )
        
        # Инициализируем воркфлоу
        orchestrator.init_workflow(file_id)
        
        # Проверяем, что воркфлоу создан
        workflow_details = db_repository.get_workflow_details(file_id)
        assert workflow_details is not None
        assert workflow_details.name == "Lecture Conspectus Workflow"
    
    def test_queue_management(self, mock_llm_client):
        """Тест управления очередью воркфлоу"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        
        initial_queue_size = orchestrator._workflow_queue.qsize()
        
        # Добавляем воркфлоу в очередь
        file_id = str(uuid.uuid4())
        orchestrator.start_orchestration(
            workflow_id=file_id,
            file_id=file_id,
            file_path="/path/to/test.mp3",
            language="ru"
        )
        
        # Проверяем, что размер очереди увеличился
        assert orchestrator._workflow_queue.qsize() > initial_queue_size
    
    def test_max_concurrent_workflows(self, mock_llm_client):
        """Тест лимита параллельных воркфлоу"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        
        assert orchestrator.max_concurrent_workflows == 3
        assert isinstance(orchestrator.max_concurrent_workflows, int)
    
    def test_active_workflows_tracking(self, mock_llm_client):
        """Тест отслеживания активных воркфлоу"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        
        assert isinstance(orchestrator.active_workflows, set)
        assert len(orchestrator.active_workflows) >= 0
    
    @pytest.mark.slow
    def test_workflow_execution_mock(self, mock_llm_client, db_repository, sample_audio_file):
        """Тест выполнения воркфлоу с моками"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        file_id = str(uuid.uuid4())
        
        # Создаём файл
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path=str(sample_audio_file),
            language="ru",
            size_bytes=sample_audio_file.stat().st_size,
            mime_type="audio/mpeg"
        )
        
        # Инициализируем воркфлоу
        orchestrator.init_workflow(file_id)
        
        # Запускаем оркестрацию
        orchestrator.start_orchestration(
            workflow_id=file_id,
            file_id=file_id,
            file_path=str(sample_audio_file),
            language="ru"
        )
        
        # Даём время на обработку
        time.sleep(2)
        
        # Проверяем, что воркфлоу добавлен в очередь или активные
        assert file_id in orchestrator.active_workflows or orchestrator._workflow_queue.qsize() > 0
    
    def test_resume_interrupted_workflows(self, mock_llm_client, db_repository, sample_audio_file):
        """Тест восстановления прерванных воркфлоу"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        file_id = str(uuid.uuid4())
        
        # Создаём файл
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path=str(sample_audio_file),
            language="ru",
            size_bytes=sample_audio_file.stat().st_size,
            mime_type="audio/mpeg"
        )
        
        # Создаём воркфлоу в статусе RUNNING
        db_repository.create_workflow(
            workflow_id=file_id,
            file_id=file_id,
            name="lecture_workflow"
        )
        db_repository.update_workflow_status(file_id, "running")
        
        # Восстанавливаем прерванные воркфлоу
        orchestrator.resume_interrupted_workflows()
        
        # Проверяем, что воркфлоу добавлен в очередь
        assert orchestrator._workflow_queue.qsize() > 0 or file_id in orchestrator.active_workflows
    
    def test_thread_safety(self, mock_llm_client):
        """Тест потокобезопасности"""
        orchestrator = LectureOrchestrator(mock_llm_client)
        
        # Проверяем наличие локов
        assert hasattr(orchestrator, '_results_lock')
        assert hasattr(orchestrator, '_queue_lock')
    
    def test_workflow_status_updates(self, mock_llm_client, db_repository):
        """Тест обновления статусов воркфлоу"""
        file_id = str(uuid.uuid4())
        
        # Создаём файл и воркфлоу
        db_repository.create_file(
            file_id=file_id,
            filename="test.mp3",
            original_path="/path/to/test.mp3",
            language="ru",
            size_bytes=1024,
            mime_type="audio/mpeg"
        )
        
        db_repository.create_workflow(
            workflow_id=file_id,
            file_id=file_id,
            name="lecture_workflow"
        )
        
        # Обновляем статус
        db_repository.update_workflow_status(file_id, "completed")
        
        # Проверяем
        workflow = db_repository.get_workflow_details(file_id)
        assert workflow.status == "completed"


@pytest.mark.integration
@pytest.mark.workflow
class TestWorkflowConverters:
    """Тесты конвертеров данных между нодами"""
    
    def test_media_converter_to_s2t(self):
        """Тест конвертера MediaConverter -> SpeechToText"""
        converter = get_converter(MediaConverterOutput, SpeechToTextInput)
        
        output = MediaConverterOutput(
            file_id="test-123",
            media_path="/path/to/converted.m4a"
        )
        
        result = converter(output)
        
        assert isinstance(result, SpeechToTextInput)
        assert result.file_id == "test-123"
        assert result.media_path == "/path/to/converted.m4a"
    
    def test_s2t_to_text_to_md(self):
        """Тест конвертера SpeechToText -> TextToMD"""
        from src.nodes.text_to_md.models import TextToMDInput
        
        converter = get_converter(SpeechToTextOutput, TextToMDInput)
        
        output = SpeechToTextOutput(
            file_id="test-123",
            txt_path="/path/to/transcription.txt"
        )
        
        result = converter(output)
        
        assert isinstance(result, TextToMDInput)
        assert result.file_id == "test-123"
        assert result.txt_path == "/path/to/transcription.txt"
    
    def test_s2t_to_text_to_latex(self):
        """Тест конвертера SpeechToText -> TextToLatex"""
        from src.nodes.text_to_latex.models import TextToLatexInput
        
        converter = get_converter(SpeechToTextOutput, TextToLatexInput)
        
        output = SpeechToTextOutput(
            file_id="test-123",
            txt_path="/path/to/transcription.txt"
        )
        
        result = converter(output)
        
        assert isinstance(result, TextToLatexInput)
        assert result.file_id == "test-123"
        assert result.txt_path == "/path/to/transcription.txt"
