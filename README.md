# 🎓 Lectify - ИИ Конспектирование

Автоматическая обработка аудио-лекций с использованием LLM: распознавание речи (STT), генерация структурированных конспектов (Markdown и LaTeX) и компиляция PDF.

## 📋 Оглавление

- [Возможности](#-возможности)
- [Архитектура](#-архитектура)
- [Установка](#-установка)
- [Использование](#-использование)
- [Структура проекта](#-структура-проекта)
- [Workflow Pipeline](#-workflow-pipeline)
- [API Endpoints](#-api-endpoints)
- [Известные проблемы](#-известные-проблемы)

## ✨ Возможности

- 🎙️ **Распознавание речи** через OpenAI Whisper (поддержка длинных аудио с автоматической сегментацией)
- 📝 **Генерация Markdown-конспектов** с использованием GPT-4o
- 📄 **Генерация LaTeX-конспектов** с автоматической классификацией предмета лекции
- 🔧 **Автоисправление LaTeX** через DeepSeek R1 (до 3 попыток при ошибках компиляции)
- 📊 **Отслеживание прогресса** через веб-интерфейс с визуализацией графа нод
- 🔄 **Восстановление после сбоев** - автоматическое продолжение прерванных воркфлоу
- ⚡ **Параллельная обработка** - до 3 файлов одновременно с автоматической очередью
- 📤 **Множественная загрузка** - загружайте несколько файлов за раз

## 🏗️ Архитектура

### Основные компоненты

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
├─────────────────────────────────────────────────────────────┤
│  Web Routes          │  API Routes        │  LLM Manager    │
│  (index, details)    │  (upload, files)   │  (smart/medium) │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              LectureOrchestrator (Singleton)                 │
│  • Управление жизненным циклом workflow                      │
│  • Рекурсивный обход графа нод                               │
│  • Многопоточное выполнение                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Workflow Graph (DAG)                      │
│                                                               │
│  MediaConverter → SpeechToText → TextToMD                    │
│                          │                                    │
│                          └──────→ TextToLatex → LatexToPDF   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    SQLite Database                           │
│  • files (исходные файлы)                                    │
│  • workflows (запуски обработки)                             │
│  • workflow_nodes (статусы нод)                              │
│  • artifacts (результаты работы нод)                         │
└─────────────────────────────────────────────────────────────┘
```

### Типизация контрактов (Pydantic)

Каждая нода работает **только** со своими строго типизированными моделями:

```python
MediaConverterInput → MediaConverterOutput
                            ↓ (converter)
                    SpeechToTextInput → SpeechToTextOutput
                            ↓ (converter)        ↓ (converter)
                    TextToMDInput          TextToLatexInput
                            ↓                     ↓
                    TextToMDOutput         TextToLatexOutput
                                                  ↓ (converter)
                                           LatexToPDFInput
                                                  ↓
                                           LatexToPDFOutput
```

**Валидация графа:** При создании `Workflow` проверяется наличие зарегистрированного конвертера для каждой связи родитель→ребёнок. Если конвертер отсутствует — выбрасывается `TypeError`.

### Ноды (BaseNode)

Все ноды наследуются от `BaseNode` и реализуют метод `run()`:

| Нода | Вход | Выход | Назначение |
|------|------|-------|------------|
| `MediaConverterNode` | `MediaConverterInput` | `MediaConverterOutput` | Конвертация аудио/видео в M4A |
| `S2TNode` | `SpeechToTextInput` | `SpeechToTextOutput` | Распознавание речи (Whisper) |
| `TextToMDNode` | `TextToMDInput` | `TextToMDOutput` | Генерация Markdown-конспекта |
| `TextToLatexNode` | `TextToLatexInput` | `TextToLatexOutput` | Генерация LaTeX-конспекта |
| `LatexToPDFNode` | `LatexToPDFInput` | `LatexToPDFOutput` | Компиляция PDF с автоисправлением |

### LLM Manager

Единый менеджер для работы с моделями через OpenAI-совместимый API:

- **smart** (`deepseek/deepseek-r1`) - сложные задачи (исправление LaTeX)
- **medium** (`openai/gpt-4o`) - быстрые задачи (Markdown-конспекты)
- **stt** (`openai/whisper-1`) - распознавание речи
- **tts** (`openai/tts-1`) - резерв для будущего

## 🚀 Установка

### Требования

- Python 3.10+
- FFmpeg (для обработки аудио/видео)
- LaTeX (для компиляции PDF)

### Шаги установки

1. **Клонирование репозитория**
```bash
git clone <repository-url>
cd lectify
```

2. **Создание виртуального окружения**
```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
# или
venv\Scripts\activate  # Windows
```

3. **Установка зависимостей**
```bash
pip install -r requirements.txt
```

⚠️ **ВНИМАНИЕ:** В `requirements.txt` ошибка - `unicorn` вместо `uvicorn`. Исправьте:
```bash
pip uninstall unicorn
pip install uvicorn
```

4. **Настройка конфигурации**
```bash
cp config.cfg.example config.cfg
# Отредактируйте config.cfg и добавьте свои API ключи
```

Пример `config.cfg`:
```ini
[OpenAI]
API_KEY = your_api_key_here
URL = https://api.openai.com/v1
```

5. **Инициализация базы данных**
```bash
mkdir -p data
# БД создастся автоматически при первом запуске
```

## 📖 Использование

### Запуск сервера

```bash
python main.py
```

Приложение будет доступно по адресу: `http://localhost:5001`

### Загрузка файла через API

```bash
curl -X POST "http://localhost:5001/upload" \
  -F "file=@lecture.mp3" \
  -F "language=ru"
```

### Поддерживаемые форматы

- Аудио: `.mp3`, `.wav`, `.m4a`
- Видео: `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`

## 📁 Структура проекта

```
lectify/
├── main.py                          # Точка входа (FastAPI + Uvicorn)
├── config.cfg                       # Конфигурация (в .gitignore)
├── config.cfg.example               # Шаблон конфига
├── requirements.txt                 # Зависимости
├── docker-compose.yml               # Стек мониторинга
├── start-monitoring.sh              # Скрипт запуска мониторинга
│
├── src/
│   ├── api/
│   │   └── routes.py                # API endpoints
│   ├── web/
│   │   └── routes.py                # Web routes
│   ├── db/
│   │   ├── database.py              # SQLAlchemy модели
│   │   ├── models.py                # Pydantic схемы
│   │   └── repository.py            # CRUD операции
│   ├── llm/
│   │   └── manager.py               # LLM клиент
│   ├── nodes/                       # Ноды обработки
│   │   ├── basenode.py
│   │   ├── media_converter/
│   │   ├── speech_to_text/
│   │   ├── text_to_md/
│   │   ├── text_to_latex/
│   │   └── latex_to_pdf/
│   ├── prompts/
│   │   └── registry.py              # Реестр промптов
│   ├── utils/
│   │   ├── logging.py               # Структурированное логирование
│   │   └── metrics.py               # Prometheus метрики
│   └── workflows/
│       ├── workflow.py              # Класс Workflow (граф нод)
│       ├── registry.py              # Реестр воркфлоу
│       ├── converter.py             # Конвертеры между моделями
│       └── orchestrator.py          # Оркестратор выполнения
│
├── resources/
│   ├── templates/                   # HTML шаблоны
│   └── prompts/                     # Системные промпты
│
├── monitoring/                      # Конфигурация мониторинга
│   ├── README.md                    # Документация мониторинга
│   ├── grafana/                     # Grafana дашборды и provisioning
│   ├── prometheus/                  # Prometheus конфиги и алерты
│   ├── loki/                        # Loki конфигурация
│   ├── promtail/                    # Promtail конфигурация
│   └── alertmanager/                # Alertmanager конфигурация
│
├── logs/                            # Логи приложения (в .gitignore)
│
└── data/                            # Данные (в .gitignore)
    ├── uploads/                     # Загруженные файлы
    └── student_bot.db               # SQLite БД
```

## 🔄 Workflow Pipeline

### 1. MediaConverter
- Конвертирует входной файл в M4A (AAC codec, 64kbps)
- Пропускает конвертацию, если файл уже в M4A

### 2. SpeechToText
- Разбивает длинные аудио на чанки по 20 минут
- Отправляет каждый чанк в Whisper API
- Объединяет результаты в единый текст

### 3. TextToMD (параллельно с TextToLatex)
- Использует GPT-4o для генерации Markdown-конспекта
- Ограничение: первые 40,000 символов текста

### 4. TextToLatex
- Классифицирует предмет лекции (chemistry, history, math, physics, sociology)
- Вызывает внешний скрипт `text_to_latex.py` с соответствующим промптом

### 5. LatexToPDF
- Компилирует LaTeX в PDF через `latex_to_pdf.py`
- При ошибке: отправляет лог и код в DeepSeek R1 для исправления
- Максимум 3 попытки автоисправления

## 🌐 API Endpoints

### Загрузка файла
```http
POST /upload
Content-Type: multipart/form-data

file: <audio/video file>
language: ru (default)
```

### Получение списка файлов
```http
GET /api/files
```

### Детали файла
```http
GET /api/files/{file_id}
```

### История воркфлоу
```http
GET /api/workflows/history
```

### Детали воркфлоу
```http
GET /api/workflows/history/{workflow_id}
```

### Скачивание артефакта
```http
GET /download/artifacts/{artifact_id}
```

### Статус очереди
```http
GET /api/queue/status
```

Возвращает:
```json
{
  "active_workflows": 2,
  "max_concurrent": 3,
  "queue_size": 5,
  "active_workflow_ids": ["uuid1", "uuid2"]
}
```

## 📊 Мониторинг и логирование

### Быстрый старт

```bash
# Запуск стека мониторинга (Grafana, Prometheus, Loki, Alertmanager)
./start-monitoring.sh

# Или вручную
docker-compose up -d
```

### Доступные сервисы

- **Grafana**: http://localhost:3000 (admin/admin) - дашборды и визуализация
- **Prometheus**: http://localhost:9090 - метрики
- **Alertmanager**: http://localhost:9093 - управление алертами
- **Loki**: http://localhost:3100 - агрегация логов
- **MinIO**: http://localhost:9001 (minioadmin/minioadmin) - объектное хранилище
- **PostgreSQL**: localhost:5432 (lectify/lectify_password) - база данных
- **Метрики приложения**: http://localhost:5001/metrics

### Хранилище данных

#### MinIO (S3-совместимое хранилище)
- **Бакет `logs`**: Логи приложения (структура: `{log_type}/{date}/{filename}`)
- **Бакет `artifacts`**: Артефакты воркфлоу (структура: `{workflow_id}/{node_id}/{type}/{filename}`)
- **Бакет `loki-data`**: Данные Loki для долгосрочного хранения

#### PostgreSQL
- **База данных**: `lectify`
- **Таблицы**: files, workflows, workflow_nodes, workflow_node_dependencies, artifacts
- **Миграции**: Alembic для управления схемой БД

### Применение миграций

```bash
# Применить все миграции
alembic upgrade head

# Откатить последнюю миграцию
alembic downgrade -1

# Создать новую миграцию
alembic revision --autogenerate -m "description"
```

### Структурированное логирование

Все логи в JSON формате с полями:
- `timestamp` - время события
- `level` - уровень (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `logger` - источник лога
- `event` - тип события
- Контекстные поля (workflow_id, file_id, node_id и т.д.)

Пример:
```json
{
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "level": "info",
  "event": "workflow_started",
  "workflow_id": "uuid",
  "active_count": 2
}
```

### Метрики

- **Воркфлоу**: общее количество, завершённые, неудачные, длительность
- **Очередь**: размер, активные воркфлоу
- **Ноды**: длительность выполнения, ошибки
- **LLM API**: запросы, длительность, ошибки
- **Система**: CPU, память, диск

### Алерты

Автоматические уведомления при:
- Недоступности приложения
- Высокой загрузке CPU/памяти
- Переполнении очереди
- Высоком проценте ошибок
- Проблемах с LLM API

Подробнее: [monitoring/README.md](monitoring/README.md)

## ⚡ Параллельная обработка

Система поддерживает одновременную обработку **до 3 файлов**. Остальные файлы автоматически добавляются в очередь.

### Как это работает

1. **Загрузка файлов** - можно загрузить несколько файлов одновременно через веб-интерфейс
2. **Автоматическая очередь** - файлы добавляются в thread-safe очередь
3. **Параллельное выполнение** - обработчик очереди запускает до 3 воркфлоу одновременно
4. **Мониторинг** - веб-интерфейс показывает количество активных и ожидающих воркфлоу

### Настройка лимита

Изменить максимальное количество параллельных воркфлоу можно в `@/Users/iizhukov/projects/lectify/src/workflows/orchestrator.py:40`:

```python
self.max_concurrent_workflows = 3  # Измените на нужное значение
```

## ✅ Исправленные проблемы

Все критические и серьёзные проблемы были исправлены:

### 🟠 Оставшиеся потенциальные улучшения

7. **Отсутствующие внешние скрипты**
   - `text_to_latex.py` и `latex_to_pdf.py` должны быть добавлены в репозиторий

8. **Busy waiting** (`orchestrator.py:147`)
   - `time.sleep(1)` в цикле можно заменить на event-driven подход

9. Отсутствие таймаутов для LLM запросов
10. Жёстко закодированные относительные пути
11. Отсутствие структурированного логирования
12. Нет валидации размера загружаемых файлов
13. Возможна утечка временных chunk-файлов при сбоях

## 🛠️ Дополнительные рекомендации

1. Добавить структурированное логирование (например, через `structlog`)
2. Реализовать event-driven подход вместо busy waiting
3. Добавить таймауты для всех внешних вызовов (LLM, subprocess)
4. Добавить валидацию размера файлов при загрузке
5. Реализовать cleanup для временных файлов через context manager
