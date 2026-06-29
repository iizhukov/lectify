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

### Оркестратор

Aсинхронный polling-цикл:

1. Каждые 5 секунд запрашивает список PENDING executions
2. Для каждого execution:
   - Топологическая сортировка графа
   - Запуск нод с учётом зависимостей
   - Глобальный семафор
   - Retry с backoff: 1s -> 2s -> 4s
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

## Установка

### Требования

- **Python 3.12+**
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

# 4. Запуск инфраструктуры
docker-compose up -d --build  # PostgreSQL, MinIO, Prometheus, Grafana

# 5. Применение миграций
alembic upgrade head

# 6. Создание начальных данных
python scripts/init_data.py

# 7. Сборка образов плагинов
python scripts/build_plugins.py

# 8. Запуск приложения
python main.py
```

**Приложение:** http://localhost:5001  
**Grafana:** http://localhost:3000 (admin/admin)  
**MinIO Console:** http://localhost:9001 (minioadmin/minioadmin)
