"""
Mock data for frontend development - Extended for new frontend
"""

import uuid
from datetime import datetime, timedelta

# =============================================
# USERS
# =============================================

MOCK_USERS = [
    {
        "id": "user-001",
        "username": "demo",
        "email": "demo@example.com",
        "full_name": "Demo User",
        "avatar_url": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-06-01T00:00:00Z"
    },
    {
        "id": "user-002",
        "username": "ivanov",
        "email": "ivanov@example.com",
        "full_name": "Иван Иванов",
        "avatar_url": None,
        "created_at": "2025-02-15T00:00:00Z",
        "updated_at": "2025-05-20T00:00:00Z"
    }
]

# Mock password hash (in real app this would be hashed)
MOCK_PASSWORD_HASH = "pbkdf2:sha256:600000$mock$hashedpassword123"

# Valid reset tokens
MOCK_RESET_TOKENS = {
    "valid-reset-token-123": {
        "user_id": "user-001",
        "expires_at": (datetime.utcnow() + timedelta(hours=1)).isoformat()
    }
}

# Active sessions (mock tokens)
MOCK_SESSIONS = {}


# =============================================
# WORKFLOWS
# =============================================

MOCK_WORKFLOWS = [
    {
        "id": "wf-001",
        "user_id": None,
        "name": "Базовая конспектация",
        "description": "Стандартный пайплайн: загрузка → транскрибация → структурирование → экспорт",
        "graph": {
            "nodes": [
                {"id": "n1", "plugin_id": "media_converter", "name": "Конвертация медиа", "description": "", "parameters": {"quality": "720p", "format": "mp4"}, "input_mapping": [], "prompt_id": None},
                {"id": "n2", "plugin_id": "transcriber", "name": "Транскрибация", "description": "", "parameters": {"model": "large", "language": "auto"}, "input_mapping": [{"target_field": "audio_data", "source": "$n1.output.audio_data", "transform": "passthrough"}], "prompt_id": None},
                {"id": "n3", "plugin_id": "formatter", "name": "Форматирование", "description": "", "parameters": {"style": "academic", "include_toc": True}, "input_mapping": [{"target_field": "transcript", "source": "$n2.output.transcript", "transform": "passthrough"}], "prompt_id": "prompt-001"},
            ],
            "edges": [
                {"from_node_id": "n1", "to_node_id": "n2"},
                {"from_node_id": "n2", "to_node_id": "n3"},
            ]
        },
        "is_public": True,
        "created_at": "2025-01-15T10:00:00Z",
        "updated_at": "2025-06-01T14:30:00Z"
    },
    {
        "id": "wf-002",
        "user_id": "user-123",
        "name": "Расширенная аналитика",
        "description": "С добавлением анализа ключевых тем и извлечением терминов",
        "graph": {
            "nodes": [
                {"id": "n1", "plugin_id": "media_converter", "name": "Конвертация медиа", "description": "", "parameters": {"quality": "720p", "format": "mp4"}, "input_mapping": [], "prompt_id": None},
                {"id": "n2", "plugin_id": "transcriber", "name": "Транскрибация", "description": "", "parameters": {"model": "large", "language": "auto"}, "input_mapping": [{"target_field": "audio_data", "source": "$n1.output.audio_data", "transform": "passthrough"}], "prompt_id": None},
                {"id": "n3", "plugin_id": "topic_analyzer", "name": "Анализ тем", "description": "", "parameters": {"num_topics": 5}, "input_mapping": [{"target_field": "text", "source": "$n2.output.transcript", "transform": "passthrough"}], "prompt_id": "prompt-002"},
                {"id": "n4", "plugin_id": "term_extractor", "name": "Извлечение терминов", "description": "", "parameters": {"max_terms": 20}, "input_mapping": [{"target_field": "text", "source": "$n2.output.transcript", "transform": "passthrough"}], "prompt_id": "prompt-003"},
                {"id": "n5", "plugin_id": "formatter", "name": "Форматирование", "description": "", "parameters": {"style": "academic", "include_toc": True}, "input_mapping": [{"target_field": "transcript", "source": "$n2.output.transcript", "transform": "passthrough"}, {"target_field": "topics", "source": "$n3.output.topics", "transform": "passthrough"}, {"target_field": "terms", "source": "$n4.output.terms", "transform": "passthrough"}], "prompt_id": "prompt-001"},
            ],
            "edges": [
                {"from_node_id": "n1", "to_node_id": "n2"},
                {"from_node_id": "n2", "to_node_id": "n3"},
                {"from_node_id": "n2", "to_node_id": "n4"},
                {"from_node_id": "n3", "to_node_id": "n5"},
                {"from_node_id": "n4", "to_node_id": "n5"},
            ]
        },
        "is_public": True,
        "created_at": "2025-03-20T09:00:00Z",
        "updated_at": "2025-05-15T11:00:00Z"
    },
    {
        "id": "wf-003",
        "user_id": "user-123",
        "name": "Быстрая транскрибация",
        "description": "Минимальный пайплайн без форматирования",
        "graph": {
            "nodes": [
                {"id": "n1", "plugin_id": "media_converter", "name": "Конвертация медиа", "description": "", "parameters": {"quality": "720p", "format": "mp4"}, "input_mapping": [], "prompt_id": None},
                {"id": "n2", "plugin_id": "transcriber", "name": "Транскрибация", "description": "", "parameters": {"model": "large", "language": "auto"}, "input_mapping": [{"target_field": "audio_data", "source": "$n1.output.audio_data", "transform": "passthrough"}], "prompt_id": None},
            ],
            "edges": [
                {"from_node_id": "n1", "to_node_id": "n2"},
            ]
        },
        "is_public": False,
        "created_at": "2025-06-10T16:00:00Z",
        "updated_at": "2025-06-10T16:00:00Z"
    }
]


# =============================================
# EXECUTIONS (with full details)
# =============================================

MOCK_EXECUTIONS = [
    {
        "id": "exec-001",
        "workflow_id": "wf-001",
        "workflow_template_id": "wf-001",
        "file_id": "file-001",
        "user_id": "user-001",
        "workflow_name": "Базовая конспектация",
        "file_name": "lecture_ai_intro.mp4",
        "language": "ru",
        "status": "completed",
        "error_message": None,
        "started_at": "2025-06-20T10:00:05Z",
        "ended_at": "2025-06-20T10:05:30Z",
        "created_at": "2025-06-20T10:00:00Z"
    },
    {
        "id": "exec-002",
        "workflow_id": "wf-002",
        "workflow_template_id": "wf-002",
        "file_id": "file-002",
        "user_id": "user-001",
        "workflow_name": "Расширенная аналитика",
        "file_name": "ml_deep_dive.mp4",
        "language": "ru",
        "status": "running",
        "error_message": None,
        "started_at": "2025-06-25T14:00:05Z",
        "ended_at": None,
        "created_at": "2025-06-25T14:00:00Z"
    },
    {
        "id": "exec-003",
        "workflow_id": "wf-001",
        "workflow_template_id": "wf-001",
        "file_id": "file-005",
        "user_id": "user-001",
        "workflow_name": "Базовая конспектация",
        "file_name": "corrupted_video.mkv",
        "language": "en",
        "status": "failed",
        "error_message": "Unsupported codec: xvid",
        "started_at": "2025-06-24T09:30:05Z",
        "ended_at": "2025-06-24T09:31:45Z",
        "created_at": "2025-06-24T09:30:00Z"
    },
    {
        "id": "exec-004",
        "workflow_id": "wf-003",
        "workflow_template_id": "wf-003",
        "file_id": "file-003",
        "user_id": "user-002",
        "workflow_name": "Быстрая транскрибация",
        "file_name": "podcast_episode_42.mp3",
        "language": "ru",
        "status": "completed",
        "error_message": None,
        "started_at": "2025-06-23T15:00:05Z",
        "ended_at": "2025-06-23T15:08:00Z",
        "created_at": "2025-06-23T15:00:00Z"
    },
    {
        "id": "exec-005",
        "workflow_id": "wf-001",
        "workflow_template_id": "wf-001",
        "file_id": "file-004",
        "user_id": "user-001",
        "workflow_name": "Базовая конспектация",
        "file_name": "webinar_storage.mp4",
        "language": "ru",
        "status": "pending",
        "error_message": None,
        "started_at": None,
        "ended_at": None,
        "created_at": "2025-06-25T15:30:00Z"
    },
    {
        "id": "exec-006",
        "workflow_id": "wf-002",
        "workflow_template_id": "wf-002",
        "file_id": "file-006",
        "user_id": "user-001",
        "workflow_name": "Расширенная аналитика",
        "file_name": "python_tutorial.mp4",
        "language": "ru",
        "status": "completed",
        "error_message": None,
        "started_at": "2025-06-22T11:00:00Z",
        "ended_at": "2025-06-22T11:25:00Z",
        "created_at": "2025-06-22T11:00:00Z"
    }
]


# =============================================
# FILES
# =============================================

MOCK_FILES = [
    {
        "id": "file-001",
        "filename": "lecture_ai_intro.mp4",
        "original_path": "minio://uploads/lecture_ai_intro.mp4",
        "language": "ru",
        "status": "processed",
        "size_bytes": 524288000,
        "mime_type": "video/mp4",
        "created_at": "2025-06-20T10:00:00Z",
        "updated_at": "2025-06-20T10:05:30Z"
    },
    {
        "id": "file-002",
        "filename": "ml_deep_dive.mp4",
        "original_path": "minio://uploads/ml_deep_dive.mp4",
        "language": "ru",
        "status": "processing",
        "size_bytes": 1073741824,
        "mime_type": "video/mp4",
        "created_at": "2025-06-25T14:00:00Z",
        "updated_at": "2025-06-25T14:02:15Z"
    },
    {
        "id": "file-003",
        "filename": "podcast_episode_42.mp3",
        "original_path": "minio://uploads/podcast_episode_42.mp3",
        "language": "ru",
        "status": "processed",
        "size_bytes": 52428800,
        "mime_type": "audio/mpeg",
        "created_at": "2025-06-23T15:00:00Z",
        "updated_at": "2025-06-23T15:08:00Z"
    },
    {
        "id": "file-004",
        "filename": "webinar_storage.mp4",
        "original_path": "minio://uploads/webinar_storage.mp4",
        "language": "ru",
        "status": "queued",
        "size_bytes": 2147483648,
        "mime_type": "video/mp4",
        "created_at": "2025-06-25T15:30:00Z",
        "updated_at": "2025-06-25T15:30:00Z"
    },
    {
        "id": "file-005",
        "filename": "corrupted_video.mkv",
        "original_path": "minio://uploads/corrupted_video.mkv",
        "language": "en",
        "status": "failed",
        "size_bytes": 104857600,
        "mime_type": "video/x-matroska",
        "created_at": "2025-06-24T09:30:00Z",
        "updated_at": "2025-06-24T09:31:45Z"
    },
    {
        "id": "file-006",
        "filename": "python_tutorial.mp4",
        "original_path": "minio://uploads/python_tutorial.mp4",
        "language": "ru",
        "status": "processed",
        "size_bytes": 786432000,
        "mime_type": "video/mp4",
        "created_at": "2025-06-22T11:00:00Z",
        "updated_at": "2025-06-22T11:25:00Z"
    }
]


# =============================================
# EXECUTION NODES (detailed with input/output)
# =============================================

MOCK_EXECUTION_NODES = {
    "exec-001": [
        {
            "id": "en-001",
            "execution_id": "exec-001",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_id": "file-001", "format": "mp4", "quality": "720p"},
            "output_data": {"output_path": "/storage/converted/file-001.mp4", "duration_seconds": 330},
            "container_id": "container-abc123",
            "cpu_percent": 15.5,
            "memory_mb": 256,
            "execution_time_ms": 1500,
            "error_message": None,
            "logs_path": "/storage/logs/exec-001/n1.log",
            "started_at": "2025-06-20T10:00:05Z",
            "ended_at": "2025-06-20T10:00:07Z",
            "created_at": "2025-06-20T10:00:05Z"
        },
        {
            "id": "en-002",
            "execution_id": "exec-001",
            "node_template_id": "node-002",
            "node_id": "n2",
            "node_name": "Транскрибация",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_path": "/storage/converted/file-001.mp4", "language": "ru"},
            "output_data": {"transcript_text": "Сегодня мы поговорим об искусственном интеллекте...", "word_count": 8500},
            "container_id": "container-def456",
            "cpu_percent": 85.2,
            "memory_mb": 2048,
            "execution_time_ms": 180000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-001/n2.log",
            "started_at": "2025-06-20T10:00:07Z",
            "ended_at": "2025-06-20T10:03:07Z",
            "created_at": "2025-06-20T10:00:07Z"
        },
        {
            "id": "en-003",
            "execution_id": "exec-001",
            "node_template_id": "node-003",
            "node_id": "n3",
            "node_name": "Форматирование",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"transcript": "Сегодня мы поговорим...", "style": "academic"},
            "output_data": {"formatted_text": "# Лекция по ИИ\n\n## Введение\n...", "format": "markdown"},
            "container_id": "container-ghi789",
            "cpu_percent": 45.0,
            "memory_mb": 512,
            "execution_time_ms": 5000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-001/n3.log",
            "started_at": "2025-06-20T10:03:07Z",
            "ended_at": "2025-06-20T10:03:12Z",
            "created_at": "2025-06-20T10:03:07Z"
        }
    ],
    "exec-002": [
        {
            "id": "en-004",
            "execution_id": "exec-002",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_id": "file-002", "format": "mp4"},
            "output_data": {"output_path": "/storage/converted/file-002.mp4"},
            "container_id": "container-jkl012",
            "cpu_percent": 12.0,
            "memory_mb": 200,
            "execution_time_ms": 2000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-002/n1.log",
            "started_at": "2025-06-25T14:00:05Z",
            "ended_at": "2025-06-25T14:00:07Z",
            "created_at": "2025-06-25T14:00:05Z"
        },
        {
            "id": "en-005",
            "execution_id": "exec-002",
            "node_template_id": "node-002",
            "node_id": "n2",
            "node_name": "Транскрибация",
            "status": "running",
            "progress_percent": 45,
            "progress_message": "Processing 00:15:30 of 00:35:00",
            "input_data": {"file_path": "/storage/converted/file-002.mp4", "language": "ru"},
            "output_data": None,
            "container_id": "container-mno345",
            "cpu_percent": 92.5,
            "memory_mb": 4096,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": "/storage/logs/exec-002/n2.log",
            "started_at": "2025-06-25T14:00:10Z",
            "ended_at": None,
            "created_at": "2025-06-25T14:00:10Z"
        },
        {
            "id": "en-006",
            "execution_id": "exec-002",
            "node_template_id": "node-004",
            "node_id": "n3",
            "node_name": "Анализ тем",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T14:00:00Z"
        },
        {
            "id": "en-007",
            "execution_id": "exec-002",
            "node_template_id": "node-005",
            "node_id": "n4",
            "node_name": "Извлечение терминов",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T14:00:00Z"
        },
        {
            "id": "en-008",
            "execution_id": "exec-002",
            "node_template_id": "node-003",
            "node_id": "n5",
            "node_name": "Форматирование",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T14:00:00Z"
        }
    ],
    "exec-003": [
        {
            "id": "en-009",
            "execution_id": "exec-003",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "failed",
            "progress_percent": 10,
            "progress_message": None,
            "input_data": {"file_id": "file-005", "format": "mp4"},
            "output_data": None,
            "container_id": "container-pqr678",
            "cpu_percent": 5.0,
            "memory_mb": 100,
            "execution_time_ms": 500,
            "error_message": "Unsupported codec: xvid. Please convert to H.264 first.",
            "logs_path": "/storage/logs/exec-003/n1.log",
            "started_at": "2025-06-24T09:30:05Z",
            "ended_at": "2025-06-24T09:31:45Z",
            "created_at": "2025-06-24T09:30:05Z"
        }
    ],
    "exec-004": [
        {
            "id": "en-010",
            "execution_id": "exec-004",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_id": "file-003", "format": "mp3"},
            "output_data": {"output_path": "/storage/converted/file-003.mp3"},
            "container_id": "container-stu901",
            "cpu_percent": 8.0,
            "memory_mb": 150,
            "execution_time_ms": 800,
            "error_message": None,
            "logs_path": "/storage/logs/exec-004/n1.log",
            "started_at": "2025-06-23T15:00:05Z",
            "ended_at": "2025-06-23T15:00:06Z",
            "created_at": "2025-06-23T15:00:05Z"
        },
        {
            "id": "en-011",
            "execution_id": "exec-004",
            "node_template_id": "node-002",
            "node_id": "n2",
            "node_name": "Транскрибация",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_path": "/storage/converted/file-003.mp3"},
            "output_data": {"transcript_text": "Добрый день! Сегодня у нас 42-й выпуск подкаста...", "word_count": 15000},
            "container_id": "container-vwx234",
            "cpu_percent": 88.0,
            "memory_mb": 2048,
            "execution_time_ms": 450000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-004/n2.log",
            "started_at": "2025-06-23T15:00:06Z",
            "ended_at": "2025-06-23T15:07:36Z",
            "created_at": "2025-06-23T15:00:06Z"
        }
    ],
    "exec-005": [
        {
            "id": "en-012",
            "execution_id": "exec-005",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T15:30:00Z"
        },
        {
            "id": "en-013",
            "execution_id": "exec-005",
            "node_template_id": "node-002",
            "node_id": "n2",
            "node_name": "Транскрибация",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T15:30:00Z"
        },
        {
            "id": "en-014",
            "execution_id": "exec-005",
            "node_template_id": "node-003",
            "node_id": "n3",
            "node_name": "Форматирование",
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": "2025-06-25T15:30:00Z"
        }
    ],
    "exec-006": [
        {
            "id": "en-015",
            "execution_id": "exec-006",
            "node_template_id": "node-001",
            "node_id": "n1",
            "node_name": "Конвертация медиа",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_id": "file-006", "format": "mp4"},
            "output_data": {"output_path": "/storage/converted/file-006.mp4"},
            "container_id": "container-yza567",
            "cpu_percent": 10.0,
            "memory_mb": 180,
            "execution_time_ms": 1200,
            "error_message": None,
            "logs_path": "/storage/logs/exec-006/n1.log",
            "started_at": "2025-06-22T11:00:05Z",
            "ended_at": "2025-06-22T11:00:06Z",
            "created_at": "2025-06-22T11:00:05Z"
        },
        {
            "id": "en-016",
            "execution_id": "exec-006",
            "node_template_id": "node-002",
            "node_id": "n2",
            "node_name": "Транскрибация",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"file_path": "/storage/converted/file-006.mp4"},
            "output_data": {"transcript_text": "В этом уроке мы разберем основы Python...", "word_count": 12000},
            "container_id": "container-bcd890",
            "cpu_percent": 90.0,
            "memory_mb": 3072,
            "execution_time_ms": 600000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-006/n2.log",
            "started_at": "2025-06-22T11:00:06Z",
            "ended_at": "2025-06-22T11:10:06Z",
            "created_at": "2025-06-22T11:00:06Z"
        },
        {
            "id": "en-017",
            "execution_id": "exec-006",
            "node_template_id": "node-004",
            "node_id": "n3",
            "node_name": "Анализ тем",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"transcript": "В этом уроке мы разберем..."},
            "output_data": {"topics": ["Переменные", "Функции", "Циклы", "Классы", "Модули"]},
            "container_id": "container-efg123",
            "cpu_percent": 30.0,
            "memory_mb": 512,
            "execution_time_ms": 8000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-006/n3.log",
            "started_at": "2025-06-22T11:10:06Z",
            "ended_at": "2025-06-22T11:10:14Z",
            "created_at": "2025-06-22T11:10:06Z"
        },
        {
            "id": "en-018",
            "execution_id": "exec-006",
            "node_template_id": "node-005",
            "node_id": "n4",
            "node_name": "Извлечение терминов",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"transcript": "В этом уроке мы разберем..."},
            "output_data": {"terms": {"def": "определение функции", "import": "импорт модуля", "class": "объявление класса"}},
            "container_id": "container-hij456",
            "cpu_percent": 25.0,
            "memory_mb": 384,
            "execution_time_ms": 6000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-006/n4.log",
            "started_at": "2025-06-22T11:10:14Z",
            "ended_at": "2025-06-22T11:10:20Z",
            "created_at": "2025-06-22T11:10:14Z"
        },
        {
            "id": "en-019",
            "execution_id": "exec-006",
            "node_template_id": "node-003",
            "node_id": "n5",
            "node_name": "Форматирование",
            "status": "completed",
            "progress_percent": 100,
            "progress_message": None,
            "input_data": {"transcript": "В этом уроке мы разберем..."},
            "output_data": {"formatted_text": "# Python Tutorial\n\n## Переменные\n...", "format": "markdown"},
            "container_id": "container-klm789",
            "cpu_percent": 20.0,
            "memory_mb": 256,
            "execution_time_ms": 4000,
            "error_message": None,
            "logs_path": "/storage/logs/exec-006/n5.log",
            "started_at": "2025-06-22T11:10:20Z",
            "ended_at": "2025-06-22T11:10:24Z",
            "created_at": "2025-06-22T11:10:20Z"
        }
    ]
}


# =============================================
# ARTIFACTS (outputs from nodes)
# =============================================

MOCK_ARTIFACTS = [
    # exec-001 artifacts
    {
        "id": "art-001",
        "execution_node_id": "en-002",
        "file_id": "file-001",
        "workflow_id": "exec-001",
        "node_id": "n2",
        "name": "transcript.txt",
        "ext": "txt",
        "artifact_type": "transcript",
        "mime_type": "text/plain",
        "path": "/storage/artifacts/exec-001/n2/transcript.txt",
        "minio_path": "artifacts/exec-001/n2/transcript.txt",
        "size_bytes": 45000,
        "created_at": "2025-06-20T10:03:00Z"
    },
    {
        "id": "art-002",
        "execution_node_id": "en-003",
        "file_id": "file-001",
        "workflow_id": "exec-001",
        "node_id": "n3",
        "name": "notes.md",
        "ext": "md",
        "artifact_type": "formatted_notes",
        "mime_type": "text/markdown",
        "path": "/storage/artifacts/exec-001/n3/notes.md",
        "minio_path": "artifacts/exec-001/n3/notes.md",
        "size_bytes": 12000,
        "created_at": "2025-06-20T10:05:00Z"
    },
    # exec-004 artifacts
    {
        "id": "art-003",
        "execution_node_id": "en-011",
        "file_id": "file-003",
        "workflow_id": "exec-004",
        "node_id": "n2",
        "name": "transcript.txt",
        "ext": "txt",
        "artifact_type": "transcript",
        "mime_type": "text/plain",
        "path": "/storage/artifacts/exec-004/n2/transcript.txt",
        "minio_path": "artifacts/exec-004/n2/transcript.txt",
        "size_bytes": 85000,
        "created_at": "2025-06-23T15:07:00Z"
    },
    # exec-006 artifacts
    {
        "id": "art-004",
        "execution_node_id": "en-016",
        "file_id": "file-006",
        "workflow_id": "exec-006",
        "node_id": "n2",
        "name": "transcript.txt",
        "ext": "txt",
        "artifact_type": "transcript",
        "mime_type": "text/plain",
        "path": "/storage/artifacts/exec-006/n2/transcript.txt",
        "minio_path": "artifacts/exec-006/n2/transcript.txt",
        "size_bytes": 68000,
        "created_at": "2025-06-22T11:10:00Z"
    },
    {
        "id": "art-005",
        "execution_node_id": "en-017",
        "file_id": "file-006",
        "workflow_id": "exec-006",
        "node_id": "n3",
        "name": "topics.json",
        "ext": "json",
        "artifact_type": "analysis",
        "mime_type": "application/json",
        "path": "/storage/artifacts/exec-006/n3/topics.json",
        "minio_path": "artifacts/exec-006/n3/topics.json",
        "size_bytes": 2500,
        "created_at": "2025-06-22T11:10:10Z"
    },
    {
        "id": "art-006",
        "execution_node_id": "en-018",
        "file_id": "file-006",
        "workflow_id": "exec-006",
        "node_id": "n4",
        "name": "terms.json",
        "ext": "json",
        "artifact_type": "analysis",
        "mime_type": "application/json",
        "path": "/storage/artifacts/exec-006/n4/terms.json",
        "minio_path": "artifacts/exec-006/n4/terms.json",
        "size_bytes": 1800,
        "created_at": "2025-06-22T11:10:15Z"
    },
    {
        "id": "art-007",
        "execution_node_id": "en-019",
        "file_id": "file-006",
        "workflow_id": "exec-006",
        "node_id": "n5",
        "name": "python_tutorial_notes.md",
        "ext": "md",
        "artifact_type": "formatted_notes",
        "mime_type": "text/markdown",
        "path": "/storage/artifacts/exec-006/n5/python_tutorial_notes.md",
        "minio_path": "artifacts/exec-006/n5/python_tutorial_notes.md",
        "size_bytes": 22000,
        "created_at": "2025-06-22T11:10:20Z"
    }
]


# =============================================
# NODE TEMPLATES
# =============================================

MOCK_NODE_TEMPLATES = [
    {
        "id": "node-001",
        "user_id": None,
        "plugin_id": "media_converter",
        "name": "Конвертация медиа",
        "description": "Конвертирует видео/аудио в стандартные форматы (MP4, MP3)",
        "parameters": {"quality": "720p", "format": "mp4"},
        "input_mapping": [],
        "prompt_id": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    },
    {
        "id": "node-002",
        "user_id": None,
        "plugin_id": "transcriber",
        "name": "Транскрибация",
        "description": "Преобразует аудио/видео в текст с помощью Whisper",
        "parameters": {"model": "large", "language": "auto"},
        "input_mapping": [],
        "prompt_id": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    },
    {
        "id": "node-003",
        "user_id": None,
        "plugin_id": "formatter",
        "name": "Форматирование",
        "description": "Структурирует текст в читаемый конспект с заголовками и списками",
        "parameters": {"style": "academic", "include_toc": True},
        "input_mapping": [],
        "prompt_id": "prompt-001",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    },
    {
        "id": "node-004",
        "user_id": None,
        "plugin_id": "topic_analyzer",
        "name": "Анализ тем",
        "description": "Выделяет ключевые темы из текста",
        "parameters": {"num_topics": 5},
        "input_mapping": [],
        "prompt_id": "prompt-002",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    },
    {
        "id": "node-005",
        "user_id": None,
        "plugin_id": "term_extractor",
        "name": "Извлечение терминов",
        "description": "Находит и объясняет специальные термины",
        "parameters": {"max_terms": 20},
        "input_mapping": [],
        "prompt_id": "prompt-003",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z"
    }
]


# =============================================
# PROMPTS
# =============================================

MOCK_PROMPTS = [
    {
        "id": "prompt-001",
        "user_id": None,
        "name": "Форматирование конспекта",
        "system_prompt": "Ты — эксперт по созданию структурированных конспектов. Создавай четкую структуру с заголовками, подзаголовками и списками.",
        "user_prompt_template": "Отформатируй следующий текст в виде конспекта:\n\n{{transcript}}\n\nТребования:\n- Используй заголовки h1, h2, h3\n- Выделяй ключевые понятия жирным\n- Добавляй bullet points для списков\n- Включи оглавление в начале",
        "variables": ["transcript"],
        "created_at": "2025-01-10T00:00:00Z",
        "updated_at": "2025-01-10T00:00:00Z"
    },
    {
        "id": "prompt-002",
        "user_id": None,
        "name": "Анализ тем",
        "system_prompt": "Ты — аналитик текста, выделяющий главные темы. Возвращай JSON с массивом тем.",
        "user_prompt_template": "Выдели 5 главных тем в следующем тексте:\n\n{{text}}\n\nДля каждой темы дай краткое описание (2-3 предложения).",
        "variables": ["text"],
        "created_at": "2025-02-15T00:00:00Z",
        "updated_at": "2025-02-15T00:00:00Z"
    },
    {
        "id": "prompt-003",
        "user_id": None,
        "name": "Извлечение терминов",
        "system_prompt": "Ты — технический писатель, объясняющий термины. Возвращай JSON с терминами.",
        "user_prompt_template": "Найди и объясни термины в тексте:\n\n{{text}}\n\nФормат:\n{\n  \"термин\": \"краткое объяснение\",\n  ...\n}",
        "variables": ["text"],
        "created_at": "2025-02-20T00:00:00Z",
        "updated_at": "2025-02-20T00:00:00Z"
    },
    {
        "id": "prompt-004",
        "user_id": "user-001",
        "name": "Краткое изложение",
        "system_prompt": "Ты — ассистент, создающий краткие резюме.",
        "user_prompt_template": "Создай краткое изложение (5-7 предложений):\n\n{{text}}",
        "variables": ["text"],
        "created_at": "2025-05-01T00:00:00Z",
        "updated_at": "2025-05-01T00:00:00Z"
    },
    {
        "id": "prompt-005",
        "user_id": None,
        "name": "Вопросы по тексту",
        "system_prompt": "Ты — преподаватель, составляющий вопросы для проверки понимания.",
        "user_prompt_template": "Составь 5 вопросов по следующему тексту:\n\n{{text}}\n\nВерни вопросы в формате:\n1. Вопрос\n2. Вопрос\n...",
        "variables": ["text"],
        "created_at": "2025-04-15T00:00:00Z",
        "updated_at": "2025-04-15T00:00:00Z"
    }
]


# =============================================
# PLUGINS
# =============================================

MOCK_PLUGINS = [
    {
        "id": "media_converter",
        "name": "Media Converter",
        "description": "Конвертация медиафайлов в стандартные форматы (MP4, MP3)",
        "version": "1.0.0",
        "node_count": 1
    },
    {
        "id": "transcriber",
        "name": "Transcriber",
        "description": "Транскрибация аудио в текст через OpenAI Whisper",
        "version": "1.0.0",
        "node_count": 1
    },
    {
        "id": "formatter",
        "name": "Formatter",
        "description": "Форматирование текста в конспект с использованием LLM",
        "version": "1.0.0",
        "node_count": 1
    },
    {
        "id": "topic_analyzer",
        "name": "Topic Analyzer",
        "description": "Анализ ключевых тем с использованием LLM",
        "version": "1.0.0",
        "node_count": 1
    },
    {
        "id": "term_extractor",
        "name": "Term Extractor",
        "description": "Извлечение и объяснение специальных терминов",
        "version": "1.0.0",
        "node_count": 1
    }
]


# =============================================
# QUEUE STATUS
# =============================================

MOCK_QUEUE_STATUS = {
    "active_workflows": 1,
    "max_concurrent": 3,
    "queue_size": 1,
    "active_workflow_ids": ["exec-002"]
}


# =============================================
# NODE LOGS (sample)
# =============================================

MOCK_NODE_LOGS = {
    "en-002": """[2025-06-20 10:00:07] INFO: Starting transcription
[2025-06-20 10:00:08] INFO: Loading audio file: /storage/converted/file-001.mp4
[2025-06-20 10:00:15] INFO: Detected language: ru
[2025-06-20 10:00:15] INFO: Using model: whisper-large-v3
[2025-06-20 10:01:30] INFO: Processing segment 1/10
[2025-06-20 10:02:45] INFO: Processing segment 5/10
[2025-06-20 10:03:05] INFO: Transcription complete
[2025-06-20 10:03:05] INFO: Words: 8500, Duration: 5:30
[2025-06-20 10:03:07] INFO: Saving transcript to /storage/artifacts/exec-001/n2/transcript.txt
""",
    "en-009": """[2025-06-24 09:30:05] INFO: Starting media conversion
[2025-06-24 09:30:06] INFO: Loading video: /storage/uploads/corrupted_video.mkv
[2025-06-24 09:30:10] ERROR: Unsupported codec: xvid
[2025-06-24 09:30:10] ERROR: Please convert source to H.264
[2025-06-24 09:31:45] INFO: Conversion failed after 100 seconds
"""
}
