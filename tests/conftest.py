"""
Pytest fixtures для интеграционных тестов
"""
import sys
import os
import subprocess
import pytest
import tempfile
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch


mock_pydub = MagicMock()
sys.modules['pydub'] = mock_pydub
mock_pydub.AudioSegment = MagicMock()

os.environ["TESTING"] = "true"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from minio import Minio

ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config import config
from src.db.database import set_testing_mode

set_testing_mode(enabled=True)

from src.db.repository import DBRepository
from src.utils.storage import MinIOStorage
from src.llm.manager import LLMManager


def get_venv_python():
    """Путь к Python в виртуальном окружении"""
    venv_python = ROOT_DIR / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    venv_python = ROOT_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def run_alembic_migrations(database_url: str):
    """Запуск миграций Alembic на указанной БД"""
    import subprocess

    venv_python = get_venv_python()

    result = subprocess.run(
        [venv_python, "-m", "alembic", "upgrade", "head"],
        env={**os.environ, "TESTING_DB_URL": database_url},
        capture_output=True,
        text=True,
        cwd=str(ROOT_DIR)
    )

    if result.returncode != 0:
        print(f"Alembic migration failed: {result.stderr}")
        print("Falling back to metadata.create_all()")
        return False

    return True


def create_test_database(database_url: str):
    """Создание тестовой БД если её нет"""
    from urllib.parse import urlparse

    parsed = urlparse(database_url)
    db_name = parsed.path.lstrip('/')

    admin_url = f"{parsed.scheme}://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as conn:
            result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.fetchone():
                conn.execute(text(f"CREATE DATABASE {db_name}"))
            else:
                print(f"ℹINFO: Test database already exists: {db_name}")
    except Exception as e:
        print(f"WARNING: Could not create database: {e}")
    finally:
        admin_engine.dispose()


@pytest.fixture(scope="session")
def test_database_url():
    """URL тестовой базы данных"""
    return config.database_test_url


@pytest.fixture(scope="session")
def test_engine(test_database_url):
    """Создание тестового engine с миграциями"""
    from sqlalchemy import create_engine, text

    create_test_database(test_database_url)

    run_alembic_migrations(test_database_url)

    engine = create_engine(
        test_database_url,
        pool_pre_ping=True,
        echo=False
    )

    yield engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))

            tables_to_clean = [
                'execution_nodes',              # зависит от executions, node_templates
                'executions',                   # зависит от workflow_templates, files, users
                'workflow_node_dependencies',   # зависит от workflow_nodes
                'workflow_nodes',               # зависит от workflows, files
                'artifacts',                    # зависит от files, workflows, workflow_nodes
                'workflows',                    # зависит от files
                'node_templates',               # зависит от plugins, prompts, users
                'workflow_templates',           # зависит от users
                'workflows_public',             # зависит от users
                'prompts',                      # зависит от users
                'plugins',
                'password_reset_tokens',        # зависит от users
                'sessions',                     # зависит от users
                'users',
                'files',
            ]

            for table in tables_to_clean:
                try:
                    conn.execute(text(f"DELETE FROM {table}"))
                except Exception as e:
                    pass

            conn.commit()
            print("🧹 Cleaned test database after all tests")
    except Exception as e:
        print(f"WARNING: Failed to clean database: {e}")

    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine):
    """
    Создание тестовой сессии с откатом транзакции после каждого теста.
    Это ПОЛНОСТЬЮ изолирует каждый тест от других.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def db_cleanup(db_session):
    """
    Fixture для очистки данных созданных тестом.
    Использовать когда тест создаёт записи через WorkflowRepository,
    который использует собственные сессии.
    """
    created_records = []

    def track_table(table_name: str):
        """Декоратор для отслеживания созданных записей"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                if result and hasattr(result, 'id'):
                    created_records.append((table_name, result.id))
                return result
            return wrapper
        return decorator

    yield created_records

    for table_name, record_id in created_records:
        try:
            db_session.execute(
                text(f"DELETE FROM {table_name} WHERE id = '{record_id}'")
            )
            db_session.commit()
        except Exception as e:
            print(f"Failed to cleanup {table_name}/{record_id}: {e}")
            db_session.rollback()


@pytest.fixture(scope="function")
def test_user(db_session, db_repository):
    """Создаёт тестового пользователя через repository (returns UserData)"""
    user = db_repository.create(
        user_id="test-user",
        username="test-user",
        email="test@example.com",
        password_hash="hashed_pwd",
    )
    return user


@pytest.fixture(scope="function")
def test_plugin(db_session):
    """Создаёт тестовый плагин для тестов"""
    from src.db.entity import DBPlugin

    existing = db_session.query(DBPlugin).filter(DBPlugin.id == "media_converter").first()
    if existing:
        return existing

    plugin = DBPlugin(
        id="media_converter",
        name="Media Converter",
        description="Конвертация медиа файлов",
        version="1.0.0",
        plugin_path="plugins/media_converter",
        input_model="MediaConverterInput",
        output_model="MediaConverterOutput",
        parameters_schema={"format": {"type": "string", "required": True}},
        is_active=True
    )
    db_session.add(plugin)
    db_session.commit()
    return plugin


@pytest.fixture(scope="function")
def db_repository(db_session):
    """
    Репозиторий использует тестовую сессию БД с откатом.
    """
    from src.db import database

    original_get_session_local = database.get_session_local

    def get_test_session_local():
        database._SessionLocal = sessionmaker(bind=db_session.bind)
        return database._SessionLocal

    database.get_session_local = get_test_session_local
    database._SessionLocal = sessionmaker(bind=db_session.bind)

    repo = DBRepository()

    yield repo

    database.get_session_local = original_get_session_local
    database._SessionLocal = original_get_session_local()


@pytest.fixture(scope="session")
def minio_client():
    """MinIO клиент для тестов"""
    try:
        client = Minio(
            config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure
        )
        client.list_buckets()
        
        return client
    except Exception as e:
        print(f"WARNING: MinIO not available: {e}")
        return None


@pytest.fixture(scope="function")
def test_storage(minio_client):
    """Тестовое хранилище MinIO или mock"""
    try:
        storage = MinIOStorage(
            endpoint=config.minio_endpoint,
            access_key=config.minio_access_key,
            secret_key=config.minio_secret_key,
            secure=config.minio_secure,
            artifacts_bucket=config.minio_artifacts_bucket,
            logs_bucket=config.minio_logs_bucket
        )

        if minio_client:
            test_buckets = ["test-artifacts", "test-logs"]
            for bucket in test_buckets:
                if not minio_client.bucket_exists(bucket):
                    minio_client.make_bucket(bucket)
            storage.artifacts_bucket = "test-artifacts"
            storage.logs_bucket = "test-logs"

        yield storage

        # Очистка после тестов
        if minio_client:
            for bucket in ["test-artifacts", "test-logs"]:
                try:
                    objects = minio_client.list_objects(bucket, recursive=True)
                    for obj in objects:
                        minio_client.remove_object(bucket, obj.object_name)
                except:
                    pass
    except Exception as e:
        print(f"WARNING: MinIO storage unavailable: {e}")
        mock_storage = MagicMock(spec=MinIOStorage)
        mock_storage.upload_artifact_from_bytes.return_value = "mock/path/test.mp3"
        yield mock_storage


@pytest.fixture
def mock_llm_client():
    """Мок LLM клиента"""
    mock = MagicMock(spec=LLMManager)
    mock.completion.return_value = "Mocked LLM response"
    return mock


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
    with open(audio_file, "wb") as f:
        f.write(b'\xff\xfb\x90\x00' * 100)
    return audio_file


@pytest.fixture
def sample_text_file(temp_dir) -> Path:
    """Создание тестового текстового файла"""
    text_file = temp_dir / "test_text.txt"
    text_file.write_text("This is a test transcription text.")
    return text_file


@pytest.fixture
def sample_markdown_file(temp_dir) -> Path:
    """Создание тестового markdown файла"""
    md_file = temp_dir / "test_summary.md"
    md_file.write_text("# Test Summary\n\nThis is a test markdown summary.")
    return md_file


@pytest.fixture(scope="function")
def test_app(db_session, mock_llm_client, test_user, test_plugin):
    """Тестовое FastAPI приложение"""
    from main import app
    from src.db import database
    from src.db.repository.base import BaseRepository

    original_get_session_local = database.get_session_local

    def get_test_session_local():
        database._SessionLocal = sessionmaker(bind=db_session.bind)
        return database._SessionLocal

    database.get_session_local = get_test_session_local
    database._SessionLocal = sessionmaker(bind=db_session.bind)

    original_session = BaseRepository.session

    @contextmanager
    def patched_session(self):
        yield db_session

    BaseRepository.session = patched_session

    try:
        yield app
    finally:
        database.get_session_local = original_get_session_local
        database._SessionLocal = original_get_session_local()
        BaseRepository.session = original_session


@pytest.fixture(scope="function")
def client(test_app, db_session):
    """Тестовый HTTP клиент"""
    with TestClient(test_app) as c:
        yield c


@pytest.fixture
def workflow_data():
    """Тестовые данные для воркфлоу"""
    return {
        "file_id": "test-file-123",
        "workflow_id": "test-workflow-456",
        "language": "ru",
        "filename": "test_lecture.mp3"
    }


@pytest.fixture(autouse=True)
def setup_logging(temp_dir):
    """Настройка логирования для тестов"""
    from src.utils.logging import setup_logging
    log_file = temp_dir / "test.log"
    setup_logging(log_level="DEBUG", log_file=str(log_file))
    return log_file


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
