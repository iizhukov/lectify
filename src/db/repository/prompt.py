from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.entity import DBPrompt


class PromptRepository(BaseRepository):

    def create(self, data: dict) -> DBPrompt:
        with self.session() as s:
            prompt = DBPrompt(**data)
            s.add(prompt)
            s.commit()
            s.refresh(prompt)
            return prompt

    def get(self, prompt_id: str) -> Optional[DBPrompt]:
        with self.session() as s:
            return s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()

    def get_by_user(self, user_id: str):
        with self.session() as s:
            return s.query(DBPrompt).filter(DBPrompt.user_id == user_id).all()

    def get_global(self):
        with self.session() as s:
            return s.query(DBPrompt).filter(DBPrompt.user_id == None).all()

    def update(self, prompt_id: str, **kwargs) -> Optional[DBPrompt]:
        with self.session() as s:
            prompt = s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return None
            for key, value in kwargs.items():
                setattr(prompt, key, value)
            s.commit()
            s.refresh(prompt)
            return prompt

    def delete(self, prompt_id: str) -> bool:
        with self.session() as s:
            prompt = s.query(DBPrompt).filter(DBPrompt.id == prompt_id).first()
            if not prompt:
                return False
            s.delete(prompt)
            s.commit()
            return True
