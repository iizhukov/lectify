#!/usr/bin/env python3
import logging
import os
import sys
from datetime import datetime, timezone


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _get_input_mapping(node_id: str) -> list:
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


def _sync_plugins_on_startup():
    from datetime import datetime
    from src.db.database import SessionLocal
    from src.db.entity import DBPlugin
    from src.plugins.registry import get_plugin_registry

    registry = get_plugin_registry()
    plugins_metadata = registry.get_plugins_metadata()

    with SessionLocal() as session:
        for metadata in plugins_metadata:
            plugin_id = metadata["id"]
            existing = session.query(DBPlugin).filter(DBPlugin.id == plugin_id).first()
            if existing:
                existing.version = metadata["version"]
                existing.parameters_schema = metadata["parameters_schema"]
                if metadata.get("color") is not None:
                    existing.color = metadata["color"]
                if metadata.get("icon_svg") is not None:
                    existing.icon_svg = metadata["icon_svg"]
                existing.updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
            else:
                now = datetime.now(timezone.utc)
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
                    created_at=now,
                    updated_at=now
                )
                session.add(plugin)
                logger.info(f"Synced plugin: {plugin_id}")
        session.commit()


def _migrate_transcription_workflow():
    from src.db.repository.workflow_template import WorkflowTemplateRepository

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
                "name": "Промпт -> Markdown",
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
        "name": "Markdown кноспект",
        "description": "Медиа -> M4A -> транскрибация -> структурированный Markdown-конспект",
        "graph": graph,
        "is_public": True
    })
    logger.info(f"Created transcription_to_markdown workflow: {workflow.id}")
    return workflow.id


def _migrate_transcription_to_pdf_workflow():
    from src.db.repository.workflow_template import WorkflowTemplateRepository

    wf_repo = WorkflowTemplateRepository()
    existing = wf_repo.get("transcription_to_pdf")
    if existing:
        logger.info("transcription_to_pdf already exists")
        return existing.id

    graph = {
        "nodes": [
            {
                "id": "input_audio_pdf",
                "plugin_id": "input",
                "name": "Входной файл",
                "parameters": {"input_type": "audio"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$__input.input_audio_pdf.file_id"},
                    {"target_field": "filename", "source": "$__input.input_audio_pdf.filename"},
                    {"target_field": "minio_path", "source": "$__input.input_audio_pdf.minio_path"},
                    {"target_field": "file_path", "source": "$__input.input_audio_pdf.file_path"},
                    {"target_field": "size", "source": "$__input.input_audio_pdf.size"},
                    {"target_field": "content_type", "source": "$__input.input_audio_pdf.content_type"}
                ]
            },
            {
                "id": "media_converter_pdf",
                "plugin_id": "media_converter",
                "name": "Конвертация медиа",
                "parameters": {"format": "m4a", "bitrate": "64k"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$input_audio_pdf.output.file_id"},
                    {"target_field": "file_path", "source": "$input_audio_pdf.output.file_path"}
                ]
            },
            {
                "id": "speech_to_text_pdf",
                "plugin_id": "speech_to_text",
                "name": "Распознавание речи",
                "parameters": {"language": "auto"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$media_converter_pdf.output.file_id"},
                    {"target_field": "media_path", "source": "$media_converter_pdf.output.media_path"}
                ]
            },
            {
                "id": "prompt_selector_latex",
                "plugin_id": "prompt_selector",
                "name": "Промпт -> LaTeX",
                "parameters": {"prompt_id": "transcript_to_latex_system"},
                "input_mapping": []
            },
            {
                "id": "text_to_latex_pdf",
                "plugin_id": "text_to_latex",
                "name": "Создание LaTeX",
                "parameters": {"subject": "auto"},
                "input_mapping": [
                    {"target_field": "txt_path", "source": "$speech_to_text_pdf.output.txt_path"},
                    {"target_field": "prompt_id", "source": "$prompt_selector_latex.output.prompt_id"}
                ]
            },
            {
                "id": "latex_to_pdf_final",
                "plugin_id": "latex_to_pdf",
                "name": "Компиляция PDF",
                "parameters": {"max_attempts": 3, "use_llm_repair": True},
                "input_mapping": [
                    {"target_field": "latex_path", "source": "$text_to_latex_pdf.output.latex_path"}
                ]
            },
        ],
        "edges": [
            {"from_node_id": "input_audio_pdf", "to_node_id": "media_converter_pdf"},
            {"from_node_id": "media_converter_pdf", "to_node_id": "speech_to_text_pdf"},
            {"from_node_id": "speech_to_text_pdf", "to_node_id": "text_to_latex_pdf"},
            {"from_node_id": "prompt_selector_latex", "to_node_id": "text_to_latex_pdf"},
            {"from_node_id": "text_to_latex_pdf", "to_node_id": "latex_to_pdf_final"},
        ]
    }

    workflow = wf_repo.create({
        "id": "transcription_to_pdf",
        "user_id": None,
        "name": "Latex PDF конспект",
        "description": "Медиа -> M4A -> транскрибация -> LaTeX -> PDF-конспект",
        "graph": graph,
        "is_public": True
    })
    logger.info(f"Created transcription_to_pdf workflow: {workflow.id}")
    return workflow.id


def _migrate_text_to_markdown_workflow():
    from src.db.repository.workflow_template import WorkflowTemplateRepository

    wf_repo = WorkflowTemplateRepository()
    existing = wf_repo.get("text_to_markdown")
    if existing:
        logger.info("text_to_markdown already exists")
        return existing.id

    graph = {
        "nodes": [
            {
                "id": "input_text",
                "plugin_id": "input",
                "name": "Входной текстовый файл",
                "parameters": {"input_type": "text"},
                "input_mapping": [
                    {"target_field": "file_id", "source": "$__input.input_text.file_id"},
                    {"target_field": "filename", "source": "$__input.input_text.filename"},
                    {"target_field": "minio_path", "source": "$__input.input_text.minio_path"},
                    {"target_field": "file_path", "source": "$__input.input_text.file_path"},
                    {"target_field": "size", "source": "$__input.input_text.size"},
                    {"target_field": "content_type", "source": "$__input.input_text.content_type"}
                ]
            },
            {
                "id": "prompt_selector_txt_md",
                "plugin_id": "prompt_selector",
                "name": "Промпт -> Markdown",
                "parameters": {"prompt_id": "text_to_md_system"},
                "input_mapping": []
            },
            {
                "id": "text_to_md_txt",
                "plugin_id": "text_to_md",
                "name": "Создание Markdown",
                "parameters": {"max_chars": 40000},
                "input_mapping": [
                    {"target_field": "txt_path", "source": "$input_text.output.file_path"},
                    {"target_field": "prompt_id", "source": "$prompt_selector_txt_md.output.prompt_id"}
                ]
            },
        ],
        "edges": [
            {"from_node_id": "input_text", "to_node_id": "text_to_md_txt"},
            {"from_node_id": "prompt_selector_txt_md", "to_node_id": "text_to_md_txt"},
        ]
    }

    workflow = wf_repo.create({
        "id": "text_to_markdown",
        "user_id": None,
        "name": "Markdown конспект из текста",
        "description": "Простое преобразование текстового файла в структурированный Markdown-конспект",
        "graph": graph,
        "is_public": True
    })
    logger.info(f"Created text_to_markdown workflow: {workflow.id}")
    return workflow.id


def run():
    if os.environ.get("TESTING") == "true":
        logger.info("Skipping init_data in test mode")
        return

    logger.info("Running database init...")

    _sync_plugins_on_startup()
    logger.info("Plugins synced")

    _migrate_transcription_workflow()
    _migrate_transcription_to_pdf_workflow()
    _migrate_text_to_markdown_workflow()
    logger.info("Workflows migrated")

    from src.db.seed import run as seed_run
    seed_run()
    logger.info("Seed data applied")

    logger.info("Database init completed")


if __name__ == "__main__":
    run()
