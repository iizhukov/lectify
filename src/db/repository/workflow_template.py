import uuid
from typing import Optional

from src.db.repository.base import BaseRepository
from src.db.entity import DBWorkflowTemplate, DBWorkflowPublic


class WorkflowTemplateRepository(BaseRepository):

    def create(self, data: dict) -> DBWorkflowTemplate:
        with self.session() as s:
            workflow = DBWorkflowTemplate(**data)
            s.add(workflow)
            s.commit()
            s.refresh(workflow)
            return workflow

    def get(self, workflow_id: str) -> Optional[DBWorkflowTemplate]:
        with self.session() as s:
            return s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()

    def get_by_user(self, user_id: str):
        with self.session() as s:
            return s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.user_id == user_id).all()

    def get_public(self):
        with self.session() as s:
            return s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.is_public == True).all()

    def update(self, workflow_id: str, **kwargs) -> Optional[DBWorkflowTemplate]:
        with self.session() as s:
            workflow = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not workflow:
                return None
            for key, value in kwargs.items():
                setattr(workflow, key, value)
            s.commit()
            s.refresh(workflow)
            return workflow

    def delete(self, workflow_id: str) -> bool:
        with self.session() as s:
            workflow = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not workflow:
                return False
            s.delete(workflow)
            s.commit()
            return True

    def publish(self, workflow_id: str) -> Optional[DBWorkflowPublic]:
        with self.session() as s:
            workflow = s.query(DBWorkflowTemplate).filter(DBWorkflowTemplate.id == workflow_id).first()
            if not workflow:
                return None
            public_wf = DBWorkflowPublic(
                id=str(uuid.uuid4()),
                original_workflow_id=workflow.id,
                name=workflow.name,
                description=workflow.description,
                graph=workflow.graph,
                author_id=workflow.user_id
            )
            s.add(public_wf)
            s.commit()
            s.refresh(public_wf)
            return public_wf

    def fork(self, public_workflow_id: str, user_id: str) -> Optional[DBWorkflowTemplate]:
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
            return private_workflow
