"""
Seed script - populates database with initial data
"""

import uuid

from src.db.database import SessionLocal
from src.db.entities import (
    DBUser, DBPlugin, DBNodeTemplate, DBPrompt,
    DBWorkflowTemplate, ExecutionStatus
)


def seed_plugins(session):
    """Create default plugins"""
    plugins = [
        {
            "id": str(uuid.uuid4()),
            "name": "media_converter",
            "description": "Converts audio/video files to various formats",
            "version": "1.0.0",
            "plugin_path": "src.nodes.media_converter",
            "input_model": "MediaConverterInput",
            "output_model": "MediaConverterOutput",
            "parameters_schema": {
                "format": {"type": "string", "default": "mp3"},
                "quality": {"type": "string", "default": "high"}
            },
            "is_active": True
        },
        {
            "id": str(uuid.uuid4()),
            "name": "speech_to_text",
            "description": "Transcribes audio to text using Whisper",
            "version": "1.0.0",
            "plugin_path": "src.nodes.speech_to_text",
            "input_model": "SpeechToTextInput",
            "output_model": "SpeechToTextOutput",
            "parameters_schema": {
                "model": {"type": "string", "default": "base"},
                "language": {"type": "string", "default": "auto"}
            },
            "is_active": True
        },
        {
            "id": str(uuid.uuid4()),
            "name": "text_to_md",
            "description": "Formats text into Markdown",
            "version": "1.0.0",
            "plugin_path": "src.nodes.text_to_md",
            "input_model": "TextToMdInput",
            "output_model": "TextToMdOutput",
            "parameters_schema": {
                "style": {"type": "string", "default": " lecture"}
            },
            "is_active": True
        },
        {
            "id": str(uuid.uuid4()),
            "name": "text_to_latex",
            "description": "Converts text to LaTeX format",
            "version": "1.0.0",
            "plugin_path": "src.nodes.text_to_latex",
            "input_model": "TextToLatexInput",
            "output_model": "TextToLatexOutput",
            "parameters_schema": {
                "template": {"type": "string", "default": "article"}
            },
            "is_active": True
        },
        {
            "id": str(uuid.uuid4()),
            "name": "latex_to_pdf",
            "description": "Compiles LaTeX to PDF",
            "version": "1.0.0",
            "plugin_path": "src.nodes.latex_to_pdf",
            "input_model": "LatexToPdfInput",
            "output_model": "LatexToPdfOutput",
            "parameters_schema": {
                "compiler": {"type": "string", "default": "pdflatex"}
            },
            "is_active": True
        },
        {
            "id": str(uuid.uuid4()),
            "name": "llm_processor",
            "description": "Processes text using LLM (DeepSeek)",
            "version": "1.0.0",
            "plugin_path": "src.nodes.llm_processor",
            "input_model": "LLMInput",
            "output_model": "LLMOutput",
            "parameters_schema": {
                "model": {"type": "string", "default": "deepseek-chat"},
                "temperature": {"type": "float", "default": 0.7}
            },
            "is_active": True
        }
    ]

    for plugin_data in plugins:
        existing = session.query(DBPlugin).filter(DBPlugin.name == plugin_data["name"]).first()
        if not existing:
            session.add(DBPlugin(**plugin_data))

    session.commit()
    return {p.name: p for p in session.query(DBPlugin).all()}


def seed_prompts(session):
    """Create default prompts"""
    prompts = [
        {
            "id": str(uuid.uuid4()),
            "name": "summarize_lecture",
            "system_prompt": "You are a helpful assistant that summarizes lecture content.",
            "user_prompt_template": "Summarize the following lecture transcript:\n\n{transcript}\n\nProvide key points and main takeaways.",
            "variables": ["transcript"]
        },
        {
            "id": str(uuid.uuid4()),
            "name": "extract_key_points",
            "system_prompt": "You are an educational assistant that extracts key concepts from text.",
            "user_prompt_template": "Extract the main concepts and definitions from:\n\n{text}",
            "variables": ["text"]
        },
        {
            "id": str(uuid.uuid4()),
            "name": "format_as_markdown",
            "system_prompt": "Format the following text as clean Markdown with headers and lists.",
            "user_prompt_template": "Format this content as Markdown:\n\n{content}",
            "variables": ["content"]
        },
        {
            "id": str(uuid.uuid4()),
            "name": "improve_clarity",
            "system_prompt": "You improve text clarity and grammar while preserving meaning.",
            "user_prompt_template": "Improve the clarity of:\n\n{text}",
            "variables": ["text"]
        }
    ]

    for prompt_data in prompts:
        existing = session.query(DBPrompt).filter(DBPrompt.name == prompt_data["name"]).first()
        if not existing:
            session.add(DBPrompt(**prompt_data))

    session.commit()
    return {p.name: p for p in session.query(DBPrompt).all()}


def seed_node_templates(session, plugins, prompts):
    """Create default node templates"""
    templates = [
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["media_converter"].id,
            "name": "Convert to Audio",
            "description": "Convert video/audio to audio format",
            "parameters": {"format": "mp3", "quality": "high"},
            "input_mapping": [
                {"target_field": "file_path", "source": "$root.file_path", "transform": "passthrough"},
                {"target_field": "format", "source": "parameters.format", "transform": "passthrough"}
            ]
        },
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["speech_to_text"].id,
            "name": "Transcribe Audio",
            "description": "Convert audio to text transcription",
            "parameters": {"model": "base"},
            "input_mapping": [
                {"target_field": "audio_path", "source": "$node.media_converter.output.path", "transform": "passthrough"}
            ]
        },
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["text_to_md"].id,
            "name": "Format as Markdown",
            "description": "Format transcription as Markdown",
            "parameters": {"style": "lecture"},
            "input_mapping": [
                {"target_field": "text", "source": "$node.speech_to_text.output.text", "transform": "passthrough"}
            ]
        },
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["llm_processor"].id,
            "name": "Summarize Content",
            "description": "Generate summary using LLM",
            "parameters": {"model": "deepseek-chat"},
            "prompt_id": prompts["summarize_lecture"].id,
            "input_mapping": [
                {"target_field": "text", "source": "$node.text_to_md.output.text", "transform": "passthrough"}
            ]
        },
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["text_to_latex"].id,
            "name": "Convert to LaTeX",
            "description": "Convert Markdown to LaTeX",
            "parameters": {"template": "article"},
            "input_mapping": [
                {"target_field": "text", "source": "$node.text_to_md.output.text", "transform": "passthrough"}
            ]
        },
        {
            "id": str(uuid.uuid4()),
            "plugin_id": plugins["latex_to_pdf"].id,
            "name": "Generate PDF",
            "description": "Compile LaTeX to PDF",
            "parameters": {"compiler": "pdflatex"},
            "input_mapping": [
                {"target_field": "tex_path", "source": "$node.text_to_latex.output.path", "transform": "passthrough"}
            ]
        }
    ]

    for template_data in templates:
        existing = session.query(DBNodeTemplate).filter(
            DBNodeTemplate.name == template_data["name"]
        ).first()
        if not existing:
            session.add(DBNodeTemplate(**template_data))

    session.commit()
    return session.query(DBNodeTemplate).all()


def seed_workflow_templates(session, node_templates):
    """Create default workflow templates"""
    # Create a basic lecture processing workflow
    template_id = str(uuid.uuid4())
    workflow = {
        "id": template_id,
        "name": "Basic Lecture Processing",
        "description": "Upload audio -> Transcribe -> Format -> Generate notes",
        "graph": {
            "nodes": [
                {"id": "media_converter", "template_id": node_templates[0].id, "position_x": 100, "position_y": 100},
                {"id": "speech_to_text", "template_id": node_templates[1].id, "position_x": 300, "position_y": 100},
                {"id": "text_to_md", "template_id": node_templates[2].id, "position_x": 500, "position_y": 100},
            ],
            "edges": [
                {"from_node": "media_converter", "to_node": "speech_to_text"},
                {"from_node": "speech_to_text", "to_node": "text_to_md"},
            ]
        },
        "is_public": True
    }

    existing = session.query(DBWorkflowTemplate).filter(
        DBWorkflowTemplate.name == workflow["name"]
    ).first()
    if not existing:
        session.add(DBWorkflowTemplate(**workflow))

    # Create full pipeline workflow
    full_workflow = {
        "id": str(uuid.uuid4()),
        "name": "Full Lecture Pipeline",
        "description": "Audio -> Transcript -> Markdown -> Summary -> LaTeX -> PDF",
        "graph": {
            "nodes": [
                {"id": "media_converter", "template_id": node_templates[0].id, "position_x": 100, "position_y": 100},
                {"id": "speech_to_text", "template_id": node_templates[1].id, "position_x": 300, "position_y": 100},
                {"id": "text_to_md", "template_id": node_templates[2].id, "position_x": 500, "position_y": 100},
                {"id": "summarize", "template_id": node_templates[3].id, "position_x": 700, "position_y": 100},
                {"id": "text_to_latex", "template_id": node_templates[4].id, "position_x": 500, "position_y": 250},
                {"id": "latex_to_pdf", "template_id": node_templates[5].id, "position_x": 700, "position_y": 250},
            ],
            "edges": [
                {"from_node": "media_converter", "to_node": "speech_to_text"},
                {"from_node": "speech_to_text", "to_node": "text_to_md"},
                {"from_node": "text_to_md", "to_node": "summarize"},
                {"from_node": "text_to_md", "to_node": "text_to_latex"},
                {"from_node": "text_to_latex", "to_node": "latex_to_pdf"},
            ]
        },
        "is_public": True
    }

    existing = session.query(DBWorkflowTemplate).filter(
        DBWorkflowTemplate.name == full_workflow["name"]
    ).first()
    if not existing:
        session.add(DBWorkflowTemplate(**full_workflow))

    session.commit()


def seed_default_user(session):
    """Create default anonymous user"""
    existing = session.query(DBUser).filter(DBUser.username == "anonymous").first()
    if not existing:
        session.add(DBUser(
            id=str(uuid.uuid4()),
            username="anonymous"
        ))
        session.commit()


def seed_all():
    """Run all seed functions"""
    session = SessionLocal()
    try:
        seed_default_user(session)
        plugins = seed_plugins(session)
        prompts = seed_prompts(session)
        node_templates = seed_node_templates(session, plugins, prompts)
        seed_workflow_templates(session, node_templates)
        print("Database seeded successfully!")
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_all()