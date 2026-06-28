import logging

from src.db.entity import DBPrompt
from src.db.database import engine
from src.prompts.registry import DEFAULT_PROMPTS, RESOURCES_PROMPTS_DIR


logger = logging.getLogger(__name__)


def migrate_prompts_to_database() -> list:
    migrated = []

    for prompt_name, prompt_content in DEFAULT_PROMPTS.items():
        prompt_id = _migrate_prompt(
            prompt_id=prompt_name,
            name=_get_display_name(prompt_name),
            content=prompt_content,
            is_system=True
        )

        if prompt_id:
            migrated.append(prompt_id)

    if RESOURCES_PROMPTS_DIR.exists():
        for prompt_file in RESOURCES_PROMPTS_DIR.glob("*.txt"):
            prompt_id = _migrate_prompt(
                prompt_id=prompt_file.stem,
                name=_get_display_name(prompt_file.stem),
                content=prompt_file.read_text(encoding="utf-8"),
                is_system=prompt_file.stem.endswith("_system")
            )

            if prompt_id:
                migrated.append(prompt_id)

    logger.info(f"Migrated {len(migrated)} prompts to database")
    return migrated


def _migrate_prompt(prompt_id: str, name: str, content: str, is_system: bool = False) -> str | None:
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from datetime import datetime

    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT id FROM prompts WHERE id = :prompt_id"), {"prompt_id": prompt_id})
        if result.fetchone():
            logger.debug(f"Prompt {prompt_id} already exists")
            return None

    minio_path = None
    if len(content) > 4096:
        minio_path = f"prompts/{prompt_id}.txt"
    elif len(content) <= 4096:
        pass

    with Session(engine) as session:
        prompt = DBPrompt(
            id=prompt_id,
            user_id=None,
            name=name,
            system_prompt=content if is_system else None,
            user_prompt_template=content if not is_system else None,
            variables=_extract_variables(content),
            minio_path=minio_path,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(prompt)
        session.commit()
        logger.info(f"Migrated prompt: {prompt_id}")
        return prompt_id


def _get_display_name(prompt_id: str) -> str:
    name_map = {
        "text_to_md_system": "Создание Markdown конспекта",
        "transcript_to_md_system": "Транскрипт → Markdown",
        "transcript_to_latex_system": "Транскрипт → LaTeX",
        "latex_classifier_system": "Классификатор предмета LaTeX",
        "latex_repair_system": "Исправление ошибок LaTeX",
    }
    return name_map.get(prompt_id, prompt_id.replace("_", " ").title())


def _extract_variables(content: str) -> list:
    import re
    variables = re.findall(r'\{\{(\w+)\}\}', content)
    return list(set(variables))


def upload_large_prompts_to_minio():
    """Upload large prompts (>4KB) to MinIO"""
    from src.utils.storage import get_storage

    storage = get_storage()
    storage.ensure_buckets()

    for prompt_file in RESOURCES_PROMPTS_DIR.glob("*.txt"):
        content = prompt_file.read_text(encoding="utf-8")
        if len(content) > 4096:
            try:
                storage.upload_artifact(
                    file_path=str(prompt_file),
                    workflow_id="prompts",
                    node_id=prompt_file.stem,
                    artifact_type="prompt"
                )

                logger.info(f"Uploaded {prompt_file.name} to MinIO")
            except Exception as e:
                logger.error(f"Failed to upload {prompt_file.name}: {e}")
