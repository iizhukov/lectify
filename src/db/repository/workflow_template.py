import uuid
from typing import Optional, List

from src.db.repository.base import BaseRepository
from src.db.entity import DBWorkflowTemplate, DBWorkflowPublic
from src.db.models.workflow_template import WorkflowTemplateModel, PublicWorkflowModel
from src.db.models.workflow_template import WorkflowGraph


def _workflow_to_model(wf: DBWorkflowTemplate) -> WorkflowTemplateModel:
    def _dt(v):
        return v.isoformat() if v else None

    graph_data = wf.graph
    if isinstance(graph_data, dict):
        graph = WorkflowGraph.model_validate(graph_data)
    else:
        graph = WorkflowGraph.model_validate({})

    return WorkflowTemplateModel(
        id=wf.id,
        user_id=wf.user_id,
        name=wf.name,
        description=wf.description,
        graph=graph,
        is_public=wf.is_public,
        created_at=_dt(wf.created_at),
        updated_at=_dt(wf.updated_at),
    )


def _public_workflow_to_model(wf: DBWorkflowPublic) -> PublicWorkflowModel:
    def _dt(v):
        return v.isoformat() if v else None

    graph_data = wf.graph
    if isinstance(graph_data, dict):
        graph = WorkflowGraph.model_validate(graph_data)
    else:
        graph = WorkflowGraph.model_validate({})

    return PublicWorkflowModel(
        id=wf.id,
        original_workflow_id=wf.original_workflow_id,
        name=wf.name,
        description=wf.description,
        graph=graph,
        author_id=wf.author_id,
        usage_count=wf.usage_count,
        created_at=_dt(wf.created_at),
    )


class WorkflowTemplateRepository(BaseRepository):

    def create(self, data: dict) -> WorkflowTemplateModel:
        with self.session() as s:
            workflow = DBWorkflowTemplate(**data)
            s.add(workflow)
            s.commit()
            s.refresh(workflow)
            return _workflow_to_model(workflow)

    def get(self, workflow_id: str) -> Optional[WorkflowTemplateModel]:
        with self.session() as s:
            wf = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not wf:
                return None
            return _workflow_to_model(wf)

    def get_by_user(self, user_id: str) -> List[WorkflowTemplateModel]:
        with self.session() as s:
            wfs = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.user_id == user_id).all()
            return [_workflow_to_model(w) for w in wfs]

    def get_public(self) -> List[WorkflowTemplateModel]:
        with self.session() as s:
            wfs = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.is_public == True).all()
            return [_workflow_to_model(w) for w in wfs]

    def update(self, workflow_id: str, **kwargs) -> Optional[WorkflowTemplateModel]:
        with self.session() as s:
            wf = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not wf:
                return None
            for key, value in kwargs.items():
                setattr(wf, key, value)
            s.commit()
            s.refresh(wf)
            return _workflow_to_model(wf)

    def delete(self, workflow_id: str) -> bool:
        with self.session() as s:
            wf = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not wf:
                return False
            s.delete(wf)
            s.commit()
            return True

    def publish(self, workflow_id: str) -> Optional[PublicWorkflowModel]:
        with self.session() as s:
            wf = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not wf:
                return None
            public_wf = DBWorkflowPublic(
                id=str(uuid.uuid4()),
                original_workflow_id=wf.id,
                name=wf.name,
                description=wf.description,
                graph=wf.graph,
                author_id=wf.user_id
            )
            s.add(public_wf)
            s.commit()
            s.refresh(public_wf)
            return _public_workflow_to_model(public_wf)

    def fork(self, public_workflow_id: str, user_id: str) -> Optional[WorkflowTemplateModel]:
        with self.session() as s:
            public_wf = s.query(DBWorkflowPublic).filter(DBWorkflowPublic.id == public_workflow_id).first()
            if not public_wf:
                return None
            public_wf.usage_count += 1
            private_workflow = DBWorkflowTemplate(
                id=str(uuid.uuid4()),
                user_id=user_id,
                name=f"{public_wf.name} (copy)",
                description=public_wf.description,
                graph=public_wf.graph,
                is_public=False
            )
            s.add(private_workflow)
            s.commit()
            s.refresh(private_workflow)
            return _workflow_to_model(private_workflow)
