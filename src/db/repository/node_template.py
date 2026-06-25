from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.entity import DBNodeTemplate


class NodeTemplateRepository(BaseRepository):

    def create(self, data: dict) -> DBNodeTemplate:
        with self.session() as s:
            template = DBNodeTemplate(**data)
            s.add(template)
            s.commit()
            s.refresh(template)
            return template

    def get(self, template_id: str) -> Optional[DBNodeTemplate]:
        with self.session() as s:
            return s.query(DBNodeTemplate).filter(DBNodeTemplate.id == template_id).first()

    def get_by_user(self, user_id: str):
        with self.session() as s:
            return s.query(DBNodeTemplate).filter(DBNodeTemplate.user_id == user_id).all()

    def get_global(self):
        with self.session() as s:
            return s.query(DBNodeTemplate).filter(DBNodeTemplate.user_id == None).all()

    def update(self, template_id: str, **kwargs) -> Optional[DBNodeTemplate]:
        with self.session() as s:
            template = s.query(DBNodeTemplate).filter(DBNodeTemplate.id == template_id).first()
            if not template:
                return None
            for key, value in kwargs.items():
                setattr(template, key, value)
            s.commit()
            s.refresh(template)
            return template
