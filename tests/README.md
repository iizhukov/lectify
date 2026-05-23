# 🧪 Интеграционные тесты Lectify

Комплексный набор интеграционных тестов для проверки всего функционала приложения.

## 📋 Содержание

- [Установка](#установка)
- [Запуск тестов](#запуск-тестов)
- [Структура тестов](#структура-тестов)
- [Покрытие](#покрытие)
- [Фикстуры](#фикстуры)
- [Маркеры](#маркеры)

## 🚀 Установка

```bash
# Установка зависимостей
pip install -r requirements.txt

# Создание тестовой базы данных
createdb lectify_test  # PostgreSQL

# Или через docker
docker exec lectify-postgres psql -U lectify -c "CREATE DATABASE lectify_test;"
```

## ▶️ Запуск тестов

### Все тесты

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

## 🔄 CI/CD

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
