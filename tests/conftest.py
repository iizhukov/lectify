"""
Pytest fixtures для интеграционных тестов
"""
import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from minio import Minio

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db.database import Base, DATABASE_URL
from src.db.repository import DBRepository
from src.utils.storage import MinIOStorage
from src.llm.manager import LLMManager


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Настройка тестовой базы данных"""
    test_db_url = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://lectify:lectify_password@localhost:5432/lectify_test"
    )
    os.environ["DATABASE_URL"] = test_db_url
    yield test_db_url


@pytest.fixture(scope="session")
def test_database_url(setup_test_database):
    """URL тестовой базы данных"""
    return setup_test_database


@pytest.fixture(scope="session")
def test_engine(test_database_url):
    """Создание тестового engine"""
    engine = create_engine(test_database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Создание тестовой сессии БД с откатом после каждого теста"""
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def db_repository():
    """Репозиторий с тестовой БД"""
    from src.db.repository import DBRepository
    repo = DBRepository()
    return repo


# =============================================================================
# MINIO FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def minio_client():
    """MinIO клиент для тестов"""
    client = Minio(
        "localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False
    )
    return client


@pytest.fixture(scope="function")
def test_storage(minio_client):
    """Тестовое хранилище MinIO"""
    storage = MinIOStorage(
        endpoint="localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False
    )
    
    # Создаём тестовые бакеты
    test_buckets = ["test-artifacts", "test-logs"]
    for bucket in test_buckets:
        if not minio_client.bucket_exists(bucket):
            minio_client.make_bucket(bucket)
    
    # Переопределяем бакеты на тестовые
    storage.artifacts_bucket = "test-artifacts"
    storage.logs_bucket = "test-logs"
    
    yield storage
    
    # Очистка после тестов
    for bucket in test_buckets:
        try:
            objects = minio_client.list_objects(bucket, recursive=True)
            for obj in objects:
                minio_client.remove_object(bucket, obj.object_name)
        except:
            pass


# =============================================================================
# LLM MOCK FIXTURES
# =============================================================================

@pytest.fixture
def mock_llm_client():
    """Мок LLM клиента"""
    mock = MagicMock(spec=LLMManager)
    
    # Мок для completion
    mock.completion.return_value = "Mocked LLM response"
    
    # Мок для audio transcription
    mock_transcription = MagicMock()
    mock_transcription.text = "Mocked transcription text"
    mock.audio = MagicMock()
    mock.audio.transcriptions = MagicMock()
    mock.audio.transcriptions.create = MagicMock(return_value=mock_transcription)
    
    return mock


# =============================================================================
# FILE FIXTURES
# =============================================================================

@pytest.fixture(scope="function")
def temp_dir() -> Generator[Path, None, None]:
    """Временная директория для тестов"""
    temp_path = Path(tempfile.mkdtemp(prefix="lectify_test_"))
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def sample_audio_file(temp_dir) -> Path:
    """Создание тестового аудио файла"""
    audio_file = temp_dir / "test_audio.mp3"
    # Создаём минимальный валидный MP3 файл
    with open(audio_file, "wb") as f:
        # MP3 header
        f.write(b'\xff\xfb\x90\x00' * 100)
    return audio_file


@pytest.fixture
def sample_text_file(temp_dir) -> Path:
    """Создание тестового текстового файла"""
    text_file = temp_dir / "test_text.txt"
    text_file.write_text("This is a test transcription text for testing purposes.")
    return text_file


@pytest.fixture
def sample_markdown_file(temp_dir) -> Path:
    """Создание тестового markdown файла"""
    md_file = temp_dir / "test_summary.md"
    md_file.write_text("# Test Summary\n\nThis is a test markdown summary.")
    return md_file


@pytest.fixture
def sample_latex_file(temp_dir) -> Path:
    """Создание тестового LaTeX файла"""
    tex_file = temp_dir / "test_lecture.tex"
    tex_file.write_text(r"""
\documentclass{article}
\begin{document}
\title{Test Lecture}
\maketitle
\section{Introduction}
This is a test lecture.
\end{document}
""")
    return tex_file


# =============================================================================
# API FIXTURES
# =============================================================================

@pytest.fixture(scope="module")
def test_app():
    """Тестовое FastAPI приложение"""
    # Патчим переменные окружения перед импортом
    os.environ["DATABASE_URL"] = "postgresql://lectify:lectify_password@localhost:5432/lectify_test"
    
    from main import app
    return app


@pytest.fixture(scope="function")
def client(test_app):
    """Тестовый HTTP клиент"""
    with TestClient(test_app) as c:
        yield c


# =============================================================================
# WORKFLOW FIXTURES
# =============================================================================

@pytest.fixture
def workflow_data():
    """Тестовые данные для воркфлоу"""
    return {
        "file_id": "test-file-123",
        "workflow_id": "test-workflow-456",
        "language": "ru",
        "filename": "test_lecture.mp3"
    }


# =============================================================================
# UTILITY FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def setup_logging(temp_dir):
    """Настройка логирования для тестов"""
    from src.utils.logging import setup_logging
    log_file = temp_dir / "test.log"
    setup_logging(log_level="DEBUG", log_file=str(log_file))
    return log_file


@pytest.fixture(autouse=True)
def reset_prometheus_registry():
    """Сброс Prometheus registry перед каждым тестом"""
    from prometheus_client import REGISTRY
    # Очищаем collectors
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except:
            pass
    yield
    # Очищаем после теста
    collectors = list(REGISTRY._collector_to_names.keys())
    for collector in collectors:
        try:
            REGISTRY.unregister(collector)
        except:
            pass


@pytest.fixture
def mock_openai_api(monkeypatch):
    """Мок OpenAI API"""
    def mock_create(*args, **kwargs):
        mock_response = MagicMock()
        mock_response.text = "Mocked transcription"
        return mock_response
    
    monkeypatch.setattr(
        "openai.resources.audio.transcriptions.Transcriptions.create",
        mock_create
    )
