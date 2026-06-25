from datetime import datetime
from typing import Optional, List

from src.db.repository.base import BaseRepository
from src.db.entity import DBNodeTemplate
from src.db.models.node_template import NodeTemplateModel


def _node_template_to_model(tmpl: DBNodeTemplate) -> NodeTemplateModel:
    def _dt(v):
        return v.isoformat() if v else None

    return NodeTemplateModel(
        id=tmpl.id,
        user_id=tmpl.user_id,
        plugin_id=tmpl.plugin_id,
        name=tmpl.name,
        description=tmpl.description,
        parameters=tmpl.parameters or {},
        input_mapping=tmpl.input_mapping,
        prompt_id=tmpl.prompt_id,
        created_at=_dt(tmpl.created_at),
        updated_at=_dt(tmpl.updated_at),
    )


class NodeTemplateRepository(BaseRepository):

    def create(self, data: dict) -> NodeTemplateModel:
        with self.session() as s:
            template = DBNodeTemplate(**data)
            s.add(template)
            s.commit()
            s.refresh(template)
            return _node_template_to_model(template)

    def get(self, template_id: str) -> Optional[NodeTemplateModel]:
        with self.session() as s:
            tmpl = s.query(DBNodeTemplate).filter(DBNodeTemplate.id == template_id).first()
            if not tmpl:
                return None
            return _node_template_to_model(tmpl)

    def get_by_user(self, user_id: str) -> List[NodeTemplateModel]:
        with self.session() as s:
            tmpls = s.query(DBNodeTemplate).filter(DBNodeTemplate.user_id == user_id).all()
            return [_node_template_to_model(t) for t in tmpls]

    def get_global(self) -> List[NodeTemplateModel]:
        with self.session() as s:
            tmpls = s.query(DBNodeTemplate).filter(DBNodeTemplate.user_id == None).all()
            return [_node_template_to_model(t) for t in tmpls]

    def update(self, template_id: str, **kwargs) -> Optional[NodeTemplateModel]:
        with self.session() as s:
            tmpl = s.query(DBNodeTemplate).filter(DBNodeTemplate.id == template_id).first()
            if not tmpl:
                return None
            for key, value in kwargs.items():
                setattr(tmpl, key, value)
            s.commit()
            s.refresh(tmpl)
            return _node_template_to_model(tmpl)
