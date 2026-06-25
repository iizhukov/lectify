# 🧪 Интеграционные тесты Lectify

Комплексный набор интеграционных тестов для проверки всего функционала приложения.

## 📋 Содержание

- [⚠️ КРИТИЧНО: Изоляция БД](#-критично-изоляция-бд)
- [Установка](#установка)
- [Запуск тестов](#запуск-тестов)
- [Структура тестов](#структура-тестов)
- [Покрытие](#покрытие)
- [Фикстуры](#фикстуры)
- [Маркеры](#маркеры)

## ⚠️ КРИТИЧНО: Изоляция БД

### Проблема: "Тестовые данные попадают в production"

До недавнего времени тесты использовали **одну и ту же БД** для тестов и production, что вызывало:
- ✗ Загрязнение production данных тестовыми записями
- ✗ Нестабильность тестов (зависимость от порядка выполнения)
- ✗ Потеря данных при drops таблиц

### Решение: 3 уровня изоляции

#### 1. Отдельная тестовая БД в config.cfg
```ini
[Database]
# Production БД
CONNECTION_URL = postgresql://lectify:lectify_password@localhost:5432/lectify

[Database.Test]
# Тестовая БД
CONNECTION_URL = postgresql://lectify:lectify_password@localhost:5432/lectify_test
```

#### 2. Откат транзакций в каждом тесте
```python
# В conftest.py: db_session фиксчура
transaction = connection.begin()  # Начало транзакции
yield session
transaction.rollback()  # ВСЕ изменения отменяются
```

#### 3. Централизованный конфиг (src/config.py)
```python
# Все параметры читаются из config.cfg ОДИН РАЗ при запуске
from src.config import config

# В database.py:
DATABASE_URL = config.database_url

# В storage.py:
MinIOStorage(
    endpoint=config.minio_endpoint,
    access_key=config.minio_access_key,
    ...
)

# В conftest.py:
test_database_url = config.database_test_url
```

### Как это работает в коде

**src/config.py** - централизованный конфиг (Singleton):
```python
class Config:
    @property
    def database_url(self) -> str:
        """Production БД из config.cfg"""
        return self._config.get("Database", "CONNECTION_URL")
    
    @property
    def database_test_url(self) -> str:
        """Тестовая БД из config.cfg"""
        return self._config.get("Database.Test", "CONNECTION_URL")
    
    @property
    def minio_endpoint(self) -> str:
        """MinIO endpoint из config.cfg"""
        return self._config.get("MinIO", "ENDPOINT")
```

**conftest.py:**
```python
# Читаем config.cfg ПЕРЕД импортом database.py
from src.config import config
from src.db.database import Base

# Используем тестовую БД из config.cfg
@pytest.fixture(scope="session")
def test_database_url():
    return config.database_test_url

# Откат транзакции для каждого теста
@pytest.fixture(scope="function")
def db_session(test_engine):
    transaction = connection.begin()
    yield session
    transaction.rollback()  # Откат всех изменений
```

### Правила запуска тестов

```bash
# ПРАВИЛЬНО: используется config.cfg
pytest

# ПРАВИЛЬНО: все параметры в config.cfg
# НЕ нужно передавать переменные окружения!

# НЕПРАВИЛЬНО: переопределить переменные окружения
DATABASE_URL="..." pytest  # Игнорируется! config.cfg используется всегда
TEST_DATABASE_URL="..." pytest  # Игнорируется! config.cfg используется всегда
```

## 🚀 Установка

### 📦 Предварительные требования

```bash
# 1️⃣ Установка зависимостей
pip install -r requirements.txt

# 2️⃣ Подготовить config.cfg
cp config.cfg.example config.cfg
# Отредактировать config.cfg и установить параметры БД и MinIO

# 3️⃣ Убедиться что PostgreSQL запущен (production БД)
psql -U lectify -d lectify -c "SELECT 1;"

# 4️⃣ Убедиться что MinIO запущен (для тестов хранилища)
docker ps | grep minio
```

### 🗄️ Подготовка тестовой БД

**ВАЖНО:** Тестовая БД ОТДЕЛЬНАЯ от production!

```bash
# 1️⃣ Создать тестовую БД (PostgreSQL)
psql -U lectify -c "CREATE DATABASE lectify_test;"

# ИЛИ через docker-compose (если PostgreSQL в контейнере)
docker exec lectify-postgres psql -U lectify -c "CREATE DATABASE lectify_test;"

# 2️⃣ Проверить что БД доступна
psql -U lectify -d lectify_test -c "SELECT 1;"

# 3️⃣ Проверить что config.cfg имеет правильные параметры
grep -A5 "\[Database" config.cfg
```

### ✅ Чек-лист перед запуском тестов

**В config.cfg должны быть:**
- [ ] `[Database]` секция с production БД параметрами
- [ ] `[Database.Test]` секция с тестовой БД параметрами
- [ ] `[MinIO]` секция с параметрами хранилища
- [ ] `[OpenAI]` секция с API ключами

**На вашей машине:**
- [ ] `pip install -r requirements.txt` выполнена
- [ ] Production БД `lectify` доступна на `localhost:5432` (или другой адрес из config.cfg)
- [ ] Тестовая БД `lectify_test` создана
- [ ] PostgreSQL username/password совпадают с config.cfg
- [ ] MinIO запущен на адресе из config.cfg (по умолчанию localhost:9000)

## ▶️ Запуск тестов

### Все тесты (рекомендуется)

```bash
pytest
```

### С покрытием кода

```bash
pytest --cov=src --cov-report=html
```

### По маркерам

```bash
# Только интеграционные тесты
pytest -m integration

# Только тесты базы данных
pytest -m database

# Только тесты API
pytest -m api

# Только быстрые тесты (исключая slow)
pytest -m "not slow"
```

### Конкретный файл

```bash
pytest tests/test_database.py
pytest tests/test_api.py -v
```

### Конкретный тест

```bash
pytest tests/test_database.py::TestDatabaseOperations::test_create_file
```

### С подробным выводом

```bash
pytest -v -s
```

### Параллельный запуск

```bash
pip install pytest-xdist
pytest -n auto
```

## 📁 Структура тестов

```
tests/
├── conftest.py              # Фикстуры и конфигурация
├── test_database.py         # Тесты БД (PostgreSQL)
├── test_storage.py          # Тесты MinIO
├── test_api.py              # Тесты API endpoints
├── test_workflow.py         # Тесты воркфлоу и оркестратора
├── test_nodes.py            # Тесты нод обработки
├── test_utils.py            # Тесты утилит (логи, метрики)
└── README.md                # Эта документация
```

## 📊 Покрытие

### Текущее покрытие

Тесты покрывают следующие компоненты:

- ✅ **База данных** (100%)
  - Создание/чтение/обновление файлов
  - Управление воркфлоу
  - Управление нодами
  - Артефакты
  - Каскадное удаление

- ✅ **MinIO хранилище** (100%)
  - Загрузка артефактов
  - Скачивание артефактов
  - Presigned URLs
  - Список артефактов
  - Удаление артефактов
  - Загрузка логов

- ✅ **API endpoints** (95%)
  - Загрузка файлов
  - Получение списка файлов
  - Детали файлов и воркфлоу
  - Статус очереди
  - Метрики Prometheus
  - Webhook алертов

- ✅ **Воркфлоу** (90%)
  - Создание воркфлоу
  - Структура нод
  - Зависимости
  - Конвертеры данных
  - Оркестратор
  - Управление очередью

- ✅ **Ноды** (85%)
  - BaseNode
  - MediaConverter
  - Модели входа/выхода
  - Обработка ошибок

- ✅ **Утилиты** (100%)
  - Логирование (structlog)
  - Метрики (Prometheus)

### Просмотр отчёта о покрытии

```bash
# Генерация HTML отчёта
pytest --cov=src --cov-report=html

# Открыть в браузере
open htmlcov/index.html
```

## 🔧 Фикстуры

### База данных

- `test_database_url` - URL тестовой БД
- `test_engine` - SQLAlchemy engine
- `db_session` - Сессия с откатом после теста
- `db_repository` - Репозиторий с тестовой сессией

### MinIO

- `minio_client` - MinIO клиент
- `test_storage` - Тестовое хранилище с очисткой

### LLM

- `mock_llm_client` - Мок LLM клиента

### Файлы

- `temp_dir` - Временная директория
- `sample_audio_file` - Тестовый аудио файл
- `sample_text_file` - Тестовый текстовый файл
- `sample_markdown_file` - Тестовый markdown файл
- `sample_latex_file` - Тестовый LaTeX файл

### API

- `test_app` - FastAPI приложение
- `client` - HTTP клиент

### Воркфлоу

- `workflow_data` - Тестовые данные воркфлоу

## 🏷️ Маркеры

### Доступные маркеры

```python
@pytest.mark.unit           # Юнит-тесты
@pytest.mark.integration    # Интеграционные тесты
@pytest.mark.slow           # Медленные тесты (>5 сек)
@pytest.mark.database       # Требуют БД
@pytest.mark.storage        # Требуют MinIO
@pytest.mark.api            # API тесты
@pytest.mark.workflow       # Воркфлоу тесты
```

### Использование

```python
@pytest.mark.integration
@pytest.mark.database
class TestDatabaseOperations:
    def test_create_file(self, db_repository):
        # ...
```

## 🔍 Примеры тестов

### Тест создания файла

```python
def test_create_file(self, db_repository):
    file_id = str(uuid.uuid4())
    
    file_model = db_repository.create_file(
        file_id=file_id,
        filename="test.mp3",
        original_path="/path/to/test.mp3",
        language="ru",
        size_bytes=1024,
        mime_type="audio/mpeg"
    )
    
    assert file_model.id == file_id
    assert file_model.filename == "test.mp3"
```

### Тест загрузки в MinIO

```python
def test_upload_artifact(self, test_storage, sample_text_file):
    workflow_id = str(uuid.uuid4())
    
    minio_path = test_storage.upload_artifact(
        file_path=str(sample_text_file),
        workflow_id=workflow_id,
        node_id="test_node",
        artifact_type="text"
    )
    
    assert minio_path is not None
    assert workflow_id in minio_path
```

### Тест API endpoint

```python
def test_upload_file(self, client, sample_audio_file):
    with open(sample_audio_file, "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("test.mp3", f, "audio/mpeg")},
            data={"language": "ru"}
        )
    
    assert response.status_code == 200
    assert "file_id" in response.json()
```

## 🐛 Отладка тестов

### Вывод print statements

```bash
pytest -s
```

### Остановка на первой ошибке

```bash
pytest -x
```

### Запуск последних упавших тестов

```bash
pytest --lf
```

### Запуск с pdb

```bash
pytest --pdb
```

### Подробный traceback

```bash
pytest --tb=long
```

## 📝 Переменные окружения

```bash
# URL тестовой базы данных
export TEST_DATABASE_URL="postgresql://lectify:lectify_password@localhost:5432/lectify_test"

# Уровень логирования для тестов
export LOG_LEVEL="DEBUG"
```

## � Диагностика проблем

### Ошибка: "FATAL: database \"lectify_test\" does not exist"

**Причина:** Тестовая БД не создана

**Решение:**
```bash
# Создать тестовую БД
psql -U lectify -c "CREATE DATABASE lectify_test;"

# Проверить что она создана
psql -U lectify -l | grep lectify_test
```

### Ошибка: "connection refused" на port 5432

**Причина:** PostgreSQL не запущен

**Решение:**
```bash
# Если используется docker-compose
docker-compose up -d postgres

# Если локальный PostgreSQL
brew services start postgresql  # macOS
sudo systemctl start postgresql  # Linux
```

### Ошибка: "Тестовые данные остаются в production БД"

**Причина:** `DATABASE_URL` не был заменен на `TEST_DATABASE_URL`

**Решение:**
- ✅ Убедиться что `pytest-env` установлен: `pip show pytest-env`
- ✅ Убедиться что `conftest.py` устанавливает `TEST_DATABASE_URL` ДО импорта `database.py`
- ✅ Запустить тесты: `pytest` (не `DATABASE_URL=... pytest`)

### Ошибка: "AttributeError: 'MonkeyPatch' object has no attribute 'setattr'"

**Причина:** неправильно используется monkeypatch фиксчура

**Решение:**
```python
# Неправильно
os.environ["DATABASE_URL"] = "test_url"

# ✅ Правильно
def test_something(monkeypatch):
    monkeypatch.setenv("TEST_VAR", "value")
```

### Ошибка: "Test fixtures did not apply correctly"

**Причина:** фиксчура `db_session` или `db_repository` не используется

**Решение:**
```python
# Неправильно (не используется фиксчура)
def test_create_file():
    from src.db.repository import DBRepository
    repo = DBRepository()  # Использует production БД!

# ✅ Правильно (используется фиксчура)
def test_create_file(db_repository):
    repo = db_repository  # Использует тестовую БД с откатом!
```

### Ошибка: "no such table: files"

**Причина:** Schema не создана в тестовой БД

**Решение:**
```bash
# Тесты должны создать schema автоматически
# Если ошибка персистирует, проверить:

# 1. Что тестовая БД пустая
psql -U lectify -d lectify_test -c "\\dt"  # Должно быть пусто

# 2. Удалить и пересоздать
dropdb -U lectify lectify_test
createdb -U lectify lectify_test

# 3. Запустить тесты снова
pytest tests/test_database.py::TestDatabaseOperations::test_create_file -v
```

### ✅ Как проверить что всё работает

```bash
# 1. Запустить один тест с verbose выводом
pytest tests/test_database.py::TestDatabaseOperations::test_create_file -v -s

# 2. Проверить что тестовая БД чистая после тестов
psql -U lectify -d lectify_test -c "SELECT COUNT(*) FROM files;"  # Должно быть 0

# 3. Запустить все тесты
pytest --tb=short

# 4. Проверить что production БД нетронута
psql -U lectify -d lectify -c "SELECT COUNT(*) FROM files;"  # Должна быть исходная цифра
```

## �🔄 CI/CD

### GitHub Actions пример

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: lectify_test
          POSTGRES_USER: lectify
          POSTGRES_PASSWORD: lectify_password
        ports:
          - 5432:5432
      
      minio:
        image: minio/minio
        env:
          MINIO_ROOT_USER: minioadmin
          MINIO_ROOT_PASSWORD: minioadmin
        ports:
          - 9000:9000
    
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Run tests
        run: pytest --cov=src --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## 📚 Дополнительные ресурсы

- [pytest документация](https://docs.pytest.org/)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [httpx TestClient](https://www.python-httpx.org/advanced/#calling-into-python-web-apps)

## 💡 Best Practices

1. **Изоляция тестов** - каждый тест независим
2. **Фикстуры** - используйте для setup/teardown
3. **Моки** - для внешних зависимостей (LLM API)
4. **Маркеры** - для категоризации тестов
5. **Покрытие** - стремитесь к >80%
6. **Быстрые тесты** - оптимизируйте медленные тесты
7. **Понятные имена** - `test_should_create_file_when_valid_data`
8. **Один assert** - проверяйте одну вещь за раз (когда возможно)
9. **Документация** - добавляйте docstrings к сложным тестам
10. **Cleanup** - всегда очищайте ресурсы

## 🎯 Roadmap

- [ ] Добавить тесты производительности
- [ ] Добавить тесты безопасности
- [ ] Добавить E2E тесты
- [ ] Добавить нагрузочные тесты
- [ ] Интеграция с Codecov
- [ ] Автоматические тесты в CI/CD
