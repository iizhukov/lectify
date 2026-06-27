"""
Workflow migration — migrate existing workflows to new architecture
"""

import logging
from datetime import datetime

from src.db.entity import DBPlugin
from src.db.repository import DBRepository
from src.db.repository.node_template import NodeTemplateRepository
from src.db.repository.workflow_template import WorkflowTemplateRepository
from src.plugins.registry import get_plugin_registry

logger = logging.getLogger(__name__)


def migrate_lecture_workflow() -> str | None:
    """
    DEPRECATED: This workflow is removed. Use transcription_to_markdown instead.

    Keeping function for backward compatibility but returns None.
    """
    logger.info("lecture_workflow migration skipped (workflow removed)")
    return None

    # Get or create default user
    default_user = repo.get_or_create_default()

    # Map old node IDs to new plugin IDs
    node_mapping = {
        "media_converter": {
            "plugin_id": "media_converter",
            "name": "Конвертация медиа",
            "parameters": {"format": "m4a", "bitrate": "64k"}
        },
        "speech_to_text": {
            "plugin_id": "speech_to_text",
            "name": "Распознавание речи",
            "parameters": {"language": "ru"}
        },
        "prompt_for_md": {
            "plugin_id": "prompt_selector",
            "name": "Промпт → Markdown",
            "parameters": {"prompt_id": ""}
        },
        "prompt_for_latex": {
            "plugin_id": "prompt_selector",
            "name": "Промпт → LaTeX",
            "parameters": {"prompt_id": ""}
        },
        "text_to_md": {
            "plugin_id": "text_to_md",
            "name": "Создание Markdown",
            "parameters": {"max_chars": 40000}
        },
        "text_to_latex": {
            "plugin_id": "text_to_latex",
            "name": "Создание LaTeX",
            "parameters": {"segments": 3, "subject": "auto"}
        },
        "latex_to_pdf": {
            "plugin_id": "latex_to_pdf",
            "name": "Компиляция PDF",
            "parameters": {"max_attempts": 3}
        }
    }

    # Create node templates
    node_template_ids = {}
    for node_id, config in node_mapping.items():
        template_id = f"{node_id}_template"
        existing_tmpl = node_repo.get(template_id)
        create_data = {
            "id": template_id,
            "user_id": None,
            "plugin_id": config["plugin_id"],
            "name": config["name"],
            "parameters": config["parameters"],
            "input_mapping": _get_input_mapping(node_id),
        }
        # Set prompt_id FK column for prompt_selector nodes
        if node_id in ("prompt_for_md", "prompt_for_latex"):
            create_data["prompt_id"] = config["parameters"].get("prompt_id")
        if existing_tmpl:
            node_template_ids[node_id] = existing_tmpl.id
        else:
            template = node_repo.create(create_data)
            node_template_ids[node_id] = template.id

    # Build workflow graph
    graph = {
        "nodes": [
            {"id": "media_converter", "plugin_id": "media_converter", "name": "Конвертация медиа", "parameters": node_mapping["media_converter"]["parameters"], "input_mapping": _get_input_mapping("media_converter")},
            {"id": "speech_to_text", "plugin_id": "speech_to_text", "name": "Распознавание речи", "parameters": node_mapping["speech_to_text"]["parameters"], "input_mapping": _get_input_mapping("speech_to_text")},
            {"id": "prompt_for_md", "plugin_id": "prompt_selector", "name": "Промпт → Markdown", "parameters": node_mapping["prompt_for_md"]["parameters"], "input_mapping": _get_input_mapping("prompt_for_md")},
            {"id": "prompt_for_latex", "plugin_id": "prompt_selector", "name": "Промпт → LaTeX", "parameters": node_mapping["prompt_for_latex"]["parameters"], "input_mapping": _get_input_mapping("prompt_for_latex")},
            {"id": "text_to_md", "plugin_id": "text_to_md", "name": "Создание Markdown", "parameters": node_mapping["text_to_md"]["parameters"], "input_mapping": _get_input_mapping("text_to_md")},
            {"id": "text_to_latex", "plugin_id": "text_to_latex", "name": "Создание LaTeX", "parameters": node_mapping["text_to_latex"]["parameters"], "input_mapping": _get_input_mapping("text_to_latex")},
            {"id": "latex_to_pdf", "plugin_id": "latex_to_pdf", "name": "Компиляция PDF", "parameters": node_mapping["latex_to_pdf"]["parameters"], "input_mapping": _get_input_mapping("latex_to_pdf")},
        ],
        "edges": [
            {"from_node_id": "media_converter", "to_node_id": "speech_to_text"},
            {"from_node_id": "speech_to_text", "to_node_id": "text_to_md"},
            {"from_node_id": "speech_to_text", "to_node_id": "text_to_latex"},
            {"from_node_id": "prompt_for_md", "to_node_id": "text_to_md"},
            {"from_node_id": "prompt_for_latex", "to_node_id": "text_to_latex"},
            {"from_node_id": "text_to_latex", "to_node_id": "latex_to_pdf"},
        ]
    }

    # Create workflow template
    workflow = wf_repo.create({
        "id": "lecture_workflow_v2",
        "user_id": None,  # Global
        "name": "Конспект лекции",
        "description": "Полный цикл: видео → M4A → текст → Markdown/LaTeX → PDF",
        "graph": graph,
        "is_public": True
    })

    logger.info(f"Migrated lecture_workflow to new format: {workflow.id}")
    return workflow.id


def _get_input_mapping(node_id: str) -> list:
    """Get input mapping for each node type"""
    mappings = {
        "speech_to_text": [
            {"target_field": "media_path", "source": "$media_converter.output.media_path"}
        ],
        "text_to_md": [
            {"target_field": "txt_path", "source": "$speech_to_text.output.txt_path"},
            {"target_field": "prompt_id", "source": "$prompt_for_md.output.prompt_id"}
        ],
        "text_to_latex": [
            {"target_field": "txt_path", "source": "$speech_to_text.output.txt_path"},
            {"target_field": "prompt_id", "source": "$prompt_for_latex.output.prompt_id"}
        ],
        "latex_to_pdf": [
            {"target_field": "latex_path", "source": "$text_to_latex.output.latex_path"}
        ],
        # Transcription to Markdown workflow
        "speech_to_text_simple": [
            {"target_field": "file_id", "source": "$media_converter_simple.output.file_id"},
            {"target_field": "media_path", "source": "$media_converter_simple.output.media_path"}
        ],
        "text_to_md_simple": [
            {"target_field": "txt_path", "source": "$speech_to_text_simple.output.txt_path"},
            {"target_field": "prompt_id", "source": "$prompt_selector_md.output.prompt_id"}
        ],
    }
    return mappings.get(node_id, [])


def migrate_transcription_workflow() -> str | None:
    """
    Create the simple transcription-to-markdown workflow with input plugin.

    Graph:
      input_audio (source) → media_converter_simple → speech_to_text_simple
                                                                    ├→ text_to_md_simple
      prompt_selector_md ───────────────────────────────────────────┘

    text_to_md_simple has two parents: speech_to_text_simple (txt_path)
    and prompt_selector_md (prompt_id from transcript_to_md_system prompt).
    """
    wf_repo = WorkflowTemplateRepository()

    existing = wf_repo.get("transcription_to_markdown")
    if existing:
        logger.info("transcription_to_markdown already exists")
        return existing.id

    graph = {
        "nodes": [
            {
                "id": "input_audio",
                "plugin_id": "input",
                "name": "Входной файл",
                "parameters": {"input_type": "audio"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$__input.input_audio.file_id"},
                    {"target_field": "filename", "source": "$__input.input_audio.filename"},
                    {"target_field": "minio_path", "source": "$__input.input_audio.minio_path"},
                    {"target_field": "file_path", "source": "$__input.input_audio.file_path"},
                    {"target_field": "size", "source": "$__input.input_audio.size"},
                    {"target_field": "content_type", "source": "$__input.input_audio.content_type"}
                ]
            },
            {
                "id": "media_converter_simple",
                "plugin_id": "media_converter",
                "name": "Конвертация медиа",
                "parameters": {"format": "m4a", "bitrate": "64k"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$input_audio.output.file_id"},
                    {"target_field": "file_path", "source": "$input_audio.output.file_path"}
                ]
            },
            {
                "id": "speech_to_text_simple",
                "plugin_id": "speech_to_text",
                "name": "Распознавание речи",
                "parameters": {"language": "auto"},
                "input_mapping": _get_input_mapping("speech_to_text_simple")
            },
            {
                "id": "prompt_selector_md",
                "plugin_id": "prompt_selector",
                "name": "Промпт → Markdown",
                "parameters": {"prompt_id": "transcript_to_md_system"},
                "input_mapping": []
            },
            {
                "id": "text_to_md_simple",
                "plugin_id": "text_to_md",
                "name": "Создание Markdown",
                "parameters": {"max_chars": 40000},
                "input_mapping": _get_input_mapping("text_to_md_simple")
            },
        ],
        "edges": [
            {"from_node_id": "input_audio", "to_node_id": "media_converter_simple"},
            {"from_node_id": "media_converter_simple", "to_node_id": "speech_to_text_simple"},
            {"from_node_id": "speech_to_text_simple", "to_node_id": "text_to_md_simple"},
            {"from_node_id": "prompt_selector_md", "to_node_id": "text_to_md_simple"},
        ]
    }

    workflow = wf_repo.create({
        "id": "transcription_to_markdown",
        "user_id": None,
        "name": "Транскрибация → Markdown",
        "description": "Медиа → M4A → транскрибация → структурированный Markdown-конспект",
        "graph": graph,
        "is_public": True
    })

    logger.info(f"Created transcription_to_markdown workflow: {workflow.id}")
    return workflow.id


def sync_plugins_on_startup():
    """
    Sync plugins from filesystem to database on application startup.

    This should be called once at startup.
    """
    from src.db.database import SessionLocal
    from datetime import datetime

    registry = get_plugin_registry()
    plugins_metadata = registry.get_plugins_metadata()

    with SessionLocal() as session:
        for metadata in plugins_metadata:
            plugin_id = metadata["id"]

            # Check if exists
            existing = session.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()

            if existing:
                # Update if needed
                existing.version = metadata["version"]
                existing.parameters_schema = metadata["parameters_schema"]
                existing.color = metadata.get("color")
                existing.icon_svg = metadata.get("icon_svg")
                existing.updated_at = datetime.utcnow()
            else:
                # Insert new
                plugin = DBPlugin(
                    id=plugin_id,
                    name=metadata["name"],
                    description=metadata["description"],
                    version=metadata["version"],
                    plugin_path=f"plugins/{plugin_id}",
                    input_model=metadata["input_model"],
                    output_model=metadata["output_model"],
                    parameters_schema=metadata["parameters_schema"],
                    color=metadata.get("color"),
                    icon_svg=metadata.get("icon_svg"),
                    is_active=True,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(plugin)
                logger.info(f"Synced plugin: {plugin_id}")

        session.commit()


def run_all_migrations():
    """
    Run all migrations on first startup.

    Call this function once at application startup.
    """
    import os

    # Skip migrations in test mode
    if os.environ.get("TESTING") == "true":
        logger.info("Skipping migrations in test mode")
        return

    logger.info("Running database migrations...")

    # 1. Sync plugins
    sync_plugins_on_startup()
    logger.info("Plugins synced")

    # 2. Migrate workflows
    migrate_transcription_workflow()
    logger.info("Workflows migrated")

    # 3. Seed initial data (idempotent)
    from src.db.seed import run as seed_run
    seed_run()
    logger.info("Seed data applied")

    logger.info("All migrations completed")