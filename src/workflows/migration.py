"""
Workflow migration — migrate existing workflows to new architecture
"""

import logging
from datetime import datetime

from src.db.entity import DBWorkflowTemplate, DBNodeTemplate, DBPlugin
from src.db.repository import DBRepository
from src.plugins.registry import get_plugin_registry

logger = logging.getLogger(__name__)


def migrate_lecture_workflow() -> str | None:
    """
    Migrate the existing lecture_workflow to new workflow_templates format.

    Returns workflow_template_id or None if already migrated.
    """
    repo = DBRepository()

    # Check if already migrated
    existing = repo.get_workflow_template("lecture_workflow_v2")
    if existing:
        logger.info("lecture_workflow already migrated")
        return existing.id

    # Get or create default user
    default_user = repo.get_or_create_default_user()

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
        template = repo.create_node_template({
            "id": f"{node_id}_template",
            "user_id": None,  # Global
            "plugin_id": config["plugin_id"],
            "name": config["name"],
            "parameters": config["parameters"],
            "input_mapping": _get_input_mapping(node_id)
        })
        node_template_ids[node_id] = template.id

    # Build workflow graph
    graph = {
        "nodes": [
            {
                "id": "media_converter",
                "template_id": node_template_ids["media_converter"],
                "position_x": 0,
                "position_y": 0
            },
            {
                "id": "speech_to_text",
                "template_id": node_template_ids["speech_to_text"],
                "position_x": 200,
                "position_y": 100
            },
            {
                "id": "text_to_md",
                "template_id": node_template_ids["text_to_md"],
                "position_x": 400,
                "position_y": 0
            },
            {
                "id": "text_to_latex",
                "template_id": node_template_ids["text_to_latex"],
                "position_x": 400,
                "position_y": 200
            },
            {
                "id": "latex_to_pdf",
                "template_id": node_template_ids["latex_to_pdf"],
                "position_x": 600,
                "position_y": 200
            }
        ],
        "edges": [
            {"from_node": "media_converter", "to_node": "speech_to_text"},
            {"from_node": "speech_to_text", "to_node": "text_to_md"},
            {"from_node": "speech_to_text", "to_node": "text_to_latex"},
            {"from_node": "text_to_latex", "to_node": "latex_to_pdf"}
        ]
    }

    # Create workflow template
    workflow = repo.create_workflow_template({
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
            {"target_field": "txt_path", "source": "$speech_to_text.output.txt_path"}
        ],
        "text_to_latex": [
            {"target_field": "txt_path", "source": "$speech_to_text.output.txt_path"}
        ],
        "latex_to_pdf": [
            {"target_field": "latex_path", "source": "$text_to_latex.output.latex_path"}
        ]
    }
    return mappings.get(node_id, [])


def sync_plugins_on_startup():
    """
    Sync plugins from filesystem to database on application startup.

    This should be called once at startup.
    """
    from src.db.database import engine
    from sqlalchemy.orm import Session
    from datetime import datetime

    registry = get_plugin_registry()
    plugins_metadata = registry.get_plugins_metadata()

    with Session(engine) as session:
        for metadata in plugins_metadata:
            plugin_id = metadata["id"]

            # Check if exists
            existing = session.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()

            if existing:
                # Update if needed
                existing.version = metadata["version"]
                existing.parameters_schema = metadata["parameters_schema"]
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

    # 2. Migrate prompts
    from src.prompts.migration import migrate_prompts_to_database
    migrate_prompts_to_database()
    logger.info("Prompts migrated")

    # 3. Migrate lecture workflow
    migrate_lecture_workflow()
    logger.info("Workflows migrated")

    logger.info("All migrations completed")