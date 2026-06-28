"""
Seed script — populates database with initial prompts and system data.
Run manually: python -m src.db.seed
"""

import sys
from pathlib import Path
from sqlalchemy.orm import Session

from src.db.database import engine
from src.db.entity import DBPrompt


PROMPTS = [
    {
        "id": "text_to_md_system",
        "name": "Создание Markdown конспекта",
        "system_prompt": (
            "Ты — опытный методист и эксперт по конспектированию. "
            "Преобразуй транскрипт лекции в структурированный Markdown-конспект: "
            "заголовки, списки, выделение ключевых понятий."
        ),
        "user_prompt_template": "{{transcript}}",
        "variables": ["transcript"],
    },
    {
        "id": "text_to_latex_system",
        "name": "Создание Latex конспекта",
        "system_prompt": (
            "Ты — опытный методист и эксперт по конспектированию. "
            "Преобразуй транскрипт лекции в структурированный Latex-конспект: "
            "заголовки, списки, выделение ключевых понятий."
        ),
        "user_prompt_template": "{{transcript}}",
        "variables": ["transcript"],
    },
    {
        "id": "latex_classifier_system",
        "name": "Классификатор предмета LaTeX",
        "system_prompt": (
            "Определи учебный предмет по тексту лекции. "
            "Верни только название предмета одним словом на английском."
        ),
        "user_prompt_template": "{{text}}",
        "variables": ["text"],
    },
    {
        "id": "latex_repair_system",
        "name": "Исправление ошибок LaTeX",
        "system_prompt": (
            "Ты — эксперт по LaTeX. Исправь ошибки компиляции в документе. "
            "Верни только исправленный LaTeX-код без пояснений."
        ),
        "user_prompt_template": "Документ:\n{{latex}}\n\nОшибки:\n{{errors}}",
        "variables": ["latex", "errors"],
    },
    {
        "id": "transcript_to_md_system",
        "name": "Markdown из транскрибации",
        "system_prompt": (
            "Ты — опытный методист и эксперт по структурированию учебного материала. "
            "Преобразуй транскрипцию лекции в красивый, структурированный Markdown-конспект. "
            "Используй заголовки ##, списки -, выделение **ключевых терминов**, "
            "логические подразделы по темам. Пиши на том же языке, на котором написан текст."
        ),
        "user_prompt_template": "{{transcript}}",
        "variables": ["transcript"],
    },
]


def seed_prompts(session: Session):
    count = 0

    for data in PROMPTS:
        existing = session.query(DBPrompt).filter(DBPrompt.id == data["id"]).first()

        if existing:
            continue

        session.add(DBPrompt(
            id=data["id"],
            user_id=None,
            name=data["name"],
            system_prompt=data["system_prompt"],
            user_prompt_template=data["user_prompt_template"],
            variables=data["variables"],
        ))

        count += 1

    session.commit()
    print(f"Seeded {count} prompt(s) (skipped {len(PROMPTS) - count} existing)")


def run():
    with Session(engine) as session:
        seed_prompts(session)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    run()
    print("Done.")
