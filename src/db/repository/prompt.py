from typing import Optional, List

from src.db.repository.base import BaseRepository
from src.db.entity import DBPrompt
from src.db.models.prompt import PromptModel


def _prompt_to_model(prompt: DBPrompt) -> PromptModel:
    def _dt(v):
        return v.isoformat() if v else None

    return PromptModel(
        id=prompt.id,
        user_id=prompt.user_id,
        name=prompt.name,
        system_prompt=prompt.system_prompt,
        user_prompt_template=prompt.user_prompt_template,
        variables=prompt.variables,
        minio_path=prompt.minio_path,
        created_at=_dt(prompt.created_at),
        updated_at=_dt(prompt.updated_at),
    )


class PromptRepository(BaseRepository):

    def create(self, data: dict) -> PromptModel:
        with self.session() as s:
            prompt = DBPrompt(**data)
            s.add(prompt)
            s.commit()
            s.refresh(prompt)
            return _prompt_to_model(prompt)

    def get(self, prompt_id: str) -> Optional[PromptModel]:
        with self.session() as s:
            prompt = s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return None
            return _prompt_to_model(prompt)

    def get_by_user(self, user_id: str) -> List[PromptModel]:
        with self.session() as s:
            prompts = s.query(DBPrompt).filter(DBPrompt.user_id == user_id).all()
            return [_prompt_to_model(p) for p in prompts]

    def get_global(self) -> List[PromptModel]:
        with self.session() as s:
            prompts = s.query(DBPrompt).filter(DBPrompt.user_id == None).all()
            return [_prompt_to_model(p) for p in prompts]

    def update(self, prompt_id: str, **kwargs) -> Optional[PromptModel]:
        with self.session() as s:
            prompt = s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return None
            for key, value in kwargs.items():
                setattr(prompt, key, value)
            s.commit()
            s.refresh(prompt)
            return _prompt_to_model(prompt)

    def delete(self, prompt_id: str) -> bool:
        with self.session() as s:
            prompt = s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return False
            s.delete(prompt)
            s.commit()
            return True
