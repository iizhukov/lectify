# 💾 Хранилище данных Lectify

Система использует MinIO для объектного хранилища и PostgreSQL для реляционных данных.

## MinIO - Объектное хранилище

### Обзор

MinIO - это S3-совместимое объектное хранилище для хранения артефактов и логов.

### Доступ

- **Console UI**: http://localhost:9001
- **API Endpoint**: http://localhost:9000
- **Credentials**: minioadmin / minioadmin

### Структура бакетов

#### 1. Бакет `artifacts`

Хранит все артефакты обработки файлов.

**Структура:**
```
artifacts/
├── {workflow_id}/
│   ├── media_converter/
│   │   └── audio/
│   │       └── converted_file.m4a
│   ├── speech_to_text/
│   │   └── text/
│   │       └── transcription.txt
│   ├── text_to_md/
│   │   └── markdown/
│   │       └── summary.md
│   ├── text_to_latex/
│   │   └── latex/
│   │       └── lecture.tex
│   └── latex_to_pdf/
│       └── pdf/
│           └── lecture.pdf
```

**Пример пути:**
```
artifacts/550e8400-e29b-41d4-a716-446655440000/speech_to_text/text/transcription.txt
```

#### 2. Бакет `logs`

Хранит логи приложения для долгосрочного хранения.

**Структура:**
```
logs/
├── application/
│   ├── 2024/
│   │   ├── 01/
│   │   │   ├── 15/
│   │   │   │   ├── lectify.log
│   │   │   │   └── lectify-error.log
```

#### 3. Бакет `loki-data`

Используется Loki для хранения индексов и чанков логов.

### Использование в коде

```python
from src.utils.storage import get_storage

# Получить клиент
storage = get_storage()

# Загрузить артефакт
minio_path = storage.upload_artifact(
    file_path="/path/to/file.pdf",
    workflow_id="550e8400-e29b-41d4-a716-446655440000",
    node_id="latex_to_pdf",
    artifact_type="pdf"
)

# Скачать артефакт
storage.download_artifact(
    object_name=minio_path,
    destination_path="/path/to/save/file.pdf"
)

# Получить presigned URL (действителен 24 часа)
url = storage.get_artifact_url(minio_path)

# Список артефактов воркфлоу
artifacts = storage.list_workflow_artifacts(workflow_id)

# Удалить все артефакты воркфлоу
storage.delete_workflow_artifacts(workflow_id)
```

### Автоматическое сохранение в нодах

Используйте метод `save_artifact` в BaseNode:

```python
class MyNode(BaseNode):
    def run(self, input_data, client):
        # ... обработка ...
        
        # Сохранить артефакт в MinIO и БД
        minio_path = self.save_artifact(
            file_id=input_data.file_id,
            workflow_id=workflow_id,
            artifact_path=output_file_path,
            artifact_type="pdf"
        )
        
        return MyNodeOutput(
            file_id=input_data.file_id,
            pdf_path=output_file_path
        )
```

### CLI команды

```bash
# Установить MinIO Client
brew install minio/stable/mc  # macOS
# или
wget https://dl.min.io/client/mc/release/linux-amd64/mc

# Настроить alias
mc alias set lectify http://localhost:9000 minioadmin minioadmin

# Список бакетов
mc ls lectify

# Список файлов в бакете
mc ls lectify/artifacts

# Скачать файл
mc cp lectify/artifacts/workflow_id/node_id/type/file.pdf ./file.pdf

# Загрузить файл
mc cp ./file.pdf lectify/artifacts/workflow_id/node_id/type/

# Удалить файл
mc rm lectify/artifacts/workflow_id/node_id/type/file.pdf

# Удалить все файлы воркфлоу
mc rm --recursive --force lectify/artifacts/workflow_id/
```

## PostgreSQL - Реляционная база данных

### Обзор

PostgreSQL используется для хранения метаданных файлов, воркфлоу и артефактов.

### Доступ

- **Host**: localhost
- **Port**: 5432
- **Database**: lectify
- **User**: lectify
- **Password**: lectify_password

### Подключение

```bash
# psql
psql -h localhost -p 5432 -U lectify -d lectify

# Python
from sqlalchemy import create_engine
engine = create_engine("postgresql://lectify:lectify_password@localhost:5432/lectify")
```

### Схема базы данных

#### Таблица `files`

Хранит информацию о загруженных файлах.

```sql
CREATE TABLE files (
    id VARCHAR PRIMARY KEY,
    filename VARCHAR NOT NULL,
    original_path VARCHAR NOT NULL,
    language VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    size_bytes INTEGER NOT NULL,
    mime_type VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### Таблица `workflows`

Хранит информацию о воркфлоу обработки.

```sql
CREATE TABLE workflows (
    id VARCHAR PRIMARY KEY,
    file_id VARCHAR NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Таблица `workflow_nodes`

Хранит состояние каждой ноды в воркфлоу.

```sql
CREATE TABLE workflow_nodes (
    id VARCHAR PRIMARY KEY,
    workflow_id VARCHAR NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    node_id VARCHAR NOT NULL,
    node_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    message TEXT,
    artifact_path VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Таблица `artifacts`

Хранит метаданные артефактов (файлы в MinIO).

```sql
CREATE TABLE artifacts (
    id VARCHAR PRIMARY KEY,
    file_id VARCHAR NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    workflow_id VARCHAR NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    node_id VARCHAR NOT NULL REFERENCES workflow_nodes(id) ON DELETE CASCADE,
    name VARCHAR NOT NULL,
    ext VARCHAR NOT NULL,
    mime_type VARCHAR NOT NULL,
    path VARCHAR NOT NULL,           -- Локальный путь (legacy)
    minio_path VARCHAR,               -- Путь в MinIO
    size_bytes INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Миграции (Alembic)

#### Создание новой миграции

```bash
# Автоматическая генерация на основе изменений моделей
alembic revision --autogenerate -m "Add new column"

# Ручное создание
alembic revision -m "Add new table"
```

#### Применение миграций

```bash
# Применить все миграции
alembic upgrade head

# Применить до конкретной версии
alembic upgrade 001

# Откатить одну миграцию
alembic downgrade -1

# Откатить до конкретной версии
alembic downgrade 001

# Показать текущую версию
alembic current

# Показать историю
alembic history
```

#### Структура миграции

```python
def upgrade() -> None:
    # Добавление колонки
    op.add_column('artifacts', sa.Column('minio_path', sa.String(), nullable=True))
    
    # Создание индекса
    op.create_index('ix_artifacts_workflow_id', 'artifacts', ['workflow_id'])
    
    # Создание таблицы
    op.create_table(
        'new_table',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade() -> None:
    # Откат изменений
    op.drop_column('artifacts', 'minio_path')
    op.drop_index('ix_artifacts_workflow_id', table_name='artifacts')
    op.drop_table('new_table')
```

### Полезные SQL запросы

```sql
-- Статистика по воркфлоу
SELECT 
    status, 
    COUNT(*) as count,
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) as avg_duration_seconds
FROM workflows
GROUP BY status;

-- Топ-10 самых больших артефактов
SELECT 
    a.name,
    a.size_bytes / 1024 / 1024 as size_mb,
    w.id as workflow_id,
    f.filename
FROM artifacts a
JOIN workflows w ON a.workflow_id = w.id
JOIN files f ON a.file_id = f.id
ORDER BY a.size_bytes DESC
LIMIT 10;

-- Артефакты конкретного воркфлоу
SELECT 
    wn.node_name,
    a.name,
    a.ext,
    a.minio_path,
    a.size_bytes
FROM artifacts a
JOIN workflow_nodes wn ON a.node_id = wn.id
WHERE a.workflow_id = 'your-workflow-id'
ORDER BY a.created_at;

-- Воркфлоу с ошибками
SELECT 
    w.id,
    f.filename,
    w.status,
    w.created_at,
    w.updated_at
FROM workflows w
JOIN files f ON w.file_id = f.id
WHERE w.status = 'failed'
ORDER BY w.created_at DESC;

-- Очистка старых данных (старше 30 дней)
DELETE FROM files 
WHERE created_at < NOW() - INTERVAL '30 days';
```

### Backup и Restore

```bash
# Backup
docker exec lectify-postgres pg_dump -U lectify lectify > backup.sql

# Restore
docker exec -i lectify-postgres psql -U lectify lectify < backup.sql

# Backup с сжатием
docker exec lectify-postgres pg_dump -U lectify lectify | gzip > backup.sql.gz

# Restore из сжатого
gunzip -c backup.sql.gz | docker exec -i lectify-postgres psql -U lectify lectify
```

## Интеграция MinIO и PostgreSQL

### Жизненный цикл артефакта

1. **Создание**: Нода создаёт файл локально
2. **Загрузка в MinIO**: `storage.upload_artifact()` загружает в MinIO
3. **Запись в БД**: `repository.create_artifact()` создаёт запись с `minio_path`
4. **Доступ**: Через presigned URL или прямое скачивание
5. **Удаление**: При удалении воркфлоу удаляются и артефакты (CASCADE)

### Пример полного цикла

```python
# 1. Создание файла
output_path = "/tmp/result.pdf"
# ... генерация PDF ...

# 2. Сохранение в MinIO и БД (автоматически)
minio_path = self.save_artifact(
    file_id=file_id,
    workflow_id=workflow_id,
    artifact_path=output_path,
    artifact_type="pdf"
)

# 3. Получение URL для скачивания
storage = get_storage()
download_url = storage.get_artifact_url(minio_path, expires_hours=24)

# 4. Список всех артефактов воркфлоу
artifacts = storage.list_workflow_artifacts(workflow_id)

# 5. Очистка (при необходимости)
storage.delete_workflow_artifacts(workflow_id)
```

## Мониторинг хранилища

### MinIO метрики

MinIO экспортирует метрики в формате Prometheus:
- `minio_bucket_usage_total_bytes` - использование бакета
- `minio_bucket_objects_count` - количество объектов
- `minio_s3_requests_total` - количество запросов

### PostgreSQL метрики

Используйте postgres_exporter для мониторинга:
- Размер базы данных
- Количество подключений
- Длительность запросов
- Размер таблиц

## Troubleshooting

### MinIO не доступен

```bash
# Проверить статус
docker-compose ps minio

# Проверить логи
docker-compose logs minio

# Перезапустить
docker-compose restart minio
```

### PostgreSQL ошибки подключения

```bash
# Проверить статус
docker-compose ps postgres

# Проверить логи
docker-compose logs postgres

# Подключиться к контейнеру
docker exec -it lectify-postgres psql -U lectify -d lectify
```

### Миграции не применяются

```bash
# Проверить текущую версию
alembic current

# Показать pending миграции
alembic history

# Применить с verbose
alembic upgrade head --sql

# Откатить и применить заново
alembic downgrade -1
alembic upgrade +1
```
