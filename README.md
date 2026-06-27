# Lectify - ИИ Конспектирование

Платформа для автоматической обработки аудио-лекций с использованием LLM: распознавание речи, генерация структурированных конспектов (Markdown и LaTeX) и компиляция PDF.

## Возможности

### Обработка медиа
- **Распознавание речи** через Whisper с автоматической сегментацией длинных аудио
- **Конвертация медиа** - поддержка аудио (MP3, WAV, M4A) и видео (MP4, MKV, AVI, MOV, WebM)
- **Автоматическая очередь** - параллельная обработка

### Надёжность и мониторинг
- **Prometheus + Grafana** - метрики в реальном времени
- **Структурированные логи** (JSON) с агрегацией через Loki
- **Alertmanager** - алерты (Telegram, email)
- **Восстановление после сбоев** - автоматическое продолжение прерванных воркфлоу
- **Отслеживание прогресса** - веб-интерфейс с визуализацией графа нод

### Хранение данных
- **PostgreSQL** - надёжное хранение метаданных
- **MinIO** (S3-совместимое) - артефакты, логи, результаты работы

## Архитектура

### Основной стек

**Backend:** FastAPI + SQLAlchemy + PostgreSQL + asyncio  
**Storage:** MinIO (S3-compatible)  
**Monitoring:** Prometheus + Grafana + Loki + Alertmanager  
**Orchestration:** Асинхронный оркестратор с очередью и retry-логикой  
**Plugins:** Docker-изолированные плагины с Pydantic-контрактами

### Компоненты системы

```
┌──────────────────────────────────────────────────────────────────┐
│                    FastAPI Application (:5001)                   │
├──────────────────────────────────────────────────────────────────┤
│  Web Routes         │  API Routes          │  LLM Manager        │
│  (SSR pages)        │  (workflows, files)  │  (smart/medium/stt) │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│           OrchestratorService (asyncio.create_task)              │
│  • Поллинг PENDING executions каждые 5 сек                       │
│  • Топологическая сортировка графа                               │
│  • Семафор на 5 одновременных нод                                │
│  • Retry с экспоненциальным backoff (до 3 попыток)               │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Plugin Execution (Docker)                     │
│                                                                  │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ media_converter│─→│speech_to_text│─→│  text_to_md  │          │
│  └────────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  Каждый плагин:                                                  │
│  • Запускается в изолированном Docker-контейнере                 │
│  • Читает input.json, пишет output.json                          │
│  • Отправляет прогресс через callback                            │
│  • Логи и артефакты сохраняются в MinIO                          │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL (:5432)          │  MinIO (:9000)                   │
│  • executions                │  • artifacts/{workflow}/{node}/  │
│  • execution_nodes           │  • logs/executions/{id}/{node}/  │
│  • workflow_templates        │                                  │
│  • files, users              │                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Оркестратор

**OrchestratorService** — асинхронный polling-цикл:

1. Каждые 5 секунд запрашивает список PENDING executions
2. Для каждого execution:
   - Топологическая сортировка графа
   - Запуск нод с учётом зависимостей
   - Глобальный семафор
   - Retry с backoff: 1s → 2s → 4s
3. Пропуск уже COMPLETED нод
4. Обновление статусов в БД в реальном времени

**ContainerRunnerOrchestrator:**
- Запускает Docker-контейнер плагина с volume mount
- Поллинг каждую секунду: CPU, память, логи
- После выполнения: загрузка артефактов и логов в MinIO

### LLM Manager

Единый клиент для работы с моделями через OpenRouter:

```python
MODELS = {
    "smart": "deepseek/deepseek-r1",     # Сложные задачи (LaTeX fix)
    "medium": "openai/gpt-4o",           # Быстрые задачи (Markdown)
    "stt": "openai/whisper-1",           # Распознавание речи
    "tts": "openai/tts-1"                # Синтез речи
}
```

**Метрики LLM:** автоматический сбор через `LLMManager.completion()`:
- `llm_api_requests_total{purpose, status}`
- `llm_api_duration_seconds{purpose}`
- `llm_api_errors_total{purpose, error_type}`

## 🚀 Установка

### Требования

- **Python 3.10+**
- **Docker + Docker Compose** (для плагинов и мониторинга)
- **FFmpeg** (для media_converter)
- **LaTeX** (для latex_to_pdf)

### Быстрый старт

```bash
# 1. Виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/macOS

# 2. Зависимости
pip install -r requirements.txt

# 3. Конфигурация
cp config.cfg.example config.cfg
# Отредактируйте config.cfg — добавьте API ключи

# 4. Запуск инфраструктуры
docker-compose up -d  --build  # PostgreSQL, MinIO, Prometheus, Grafana

# 5. Применение миграций
alembic upgrade head

# 6. Запуск приложения
python main.py
```

**Приложение:** http://localhost:5001  
**Grafana:** http://localhost:3000 (admin/admin)  
**MinIO Console:** http://localhost:9001 (minioadmin/minioadmin)

## 📊 Мониторинг

### Метрики (Prometheus)

**Воркфлоу:**
- `workflows_total` - общее количество запущенных
- `workflows_completed_total` - успешно завершённые
- `workflows_failed_total` - неудачные
- `workflow_duration_seconds` - длительность выполнения
- `workflow_queue_size` - размер очереди
- `workflow_active_count` - активные воркфлоу

**Ноды:**
- `node_execution_duration_seconds{node_id, plugin_id}`
- `node_failures_total{node_id, plugin_id}`
- `node_cpu_percent{node_id}` - CPU в реальном времени
- `node_memory_mb{node_id}` - память в реальном времени

**LLM API:**
- `llm_api_requests_total{purpose, status}`
- `llm_api_duration_seconds{purpose}`
- `llm_api_errors_total{purpose, error_type}`

**Файлы:**
- `files_uploaded_total`
- `file_size_bytes` (histogram)

### Логи (Loki)

Все логи в JSON-формате со структурированными полями:

```json
{
  "timestamp": "2026-06-27T02:15:30.123Z",
  "level": "info",
  "logger": "src.orchestrator.service",
  "event": "node_execution_started",
  "execution_id": "uuid",
  "node_id": "speech_to_text",
  "plugin_id": "speech_to_text"
}
```
