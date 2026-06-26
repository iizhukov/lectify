from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import joinedload

from src.db.repository.base import BaseRepository
from src.db.entity import DBExecution, DBExecutionNode
from src.db.models.execution import ExecutionModel, ExecutionNodeModel
from src.db.models.workflow_template import WorkflowTemplateModel


def _node_to_model(node: DBExecutionNode) -> ExecutionNodeModel:
    def _dt(v):
        return v.isoformat() if v else None

    return ExecutionNodeModel(
        id=node.id,
        execution_id=node.execution_id,
        node_template_id=node.node_template_id,
        node_id=node.node_id,
        node_name=node.node_name or "",
        status=node.status,
        progress_percent=node.progress_percent,
        progress_message=node.progress_message,
        input_data=node.input_data,
        output_data=node.output_data,
        container_id=node.container_id,
        cpu_percent=node.cpu_percent,
        memory_mb=node.memory_mb,
        execution_time_ms=node.execution_time_ms,
        error_message=node.error_message,
        logs_path=node.logs_path,
        started_at=_dt(node.started_at),
        ended_at=_dt(node.ended_at),
        created_at=_dt(node.created_at),
    )


def _execution_to_model(exec: DBExecution) -> ExecutionModel:
    def _dt(v):
        return v.isoformat() if v else None

    nodes = [_node_to_model(n) for n in exec.nodes] if exec.nodes else None

    workflow_template = None
    if exec.workflow_template:
        wt = exec.workflow_template
        workflow_template = WorkflowTemplateModel(
            id=wt.id,
            user_id=wt.user_id,
            name=wt.name or "",
            description=wt.description,
            graph=wt.graph,
            is_public=wt.is_public or False,
            created_at=_dt(wt.created_at),
            updated_at=_dt(wt.updated_at) if hasattr(wt, 'updated_at') else None,
        )

    return ExecutionModel(
        id=exec.id,
        workflow_template_id=exec.workflow_template_id,
        file_id=exec.file_id,
        user_id=exec.user_id,
        workflow_name=exec.workflow_name,
        file_name=exec.file_name,
        language=exec.language or "ru",
        status=exec.status,
        started_at=_dt(exec.started_at),
        ended_at=_dt(exec.ended_at),
        error_message=exec.error_message,
        created_at=_dt(exec.created_at),
        nodes=nodes,
        workflow_template=workflow_template,
    )


class ExecutionRepository(BaseRepository):

    def create(self, data: dict) -> ExecutionModel:
        with self.session() as s:
            execution = DBExecution(**data)
            s.add(execution)
            s.commit()
            s.refresh(execution)
            return _execution_to_model(execution)

    def get(self, execution_id: str) -> Optional[ExecutionModel]:
        with self.session() as s:
            exec = s.query(DBExecution).options(
                joinedload(DBExecution.nodes),
                joinedload(DBExecution.workflow_template),
            ).filter(DBExecution.id == execution_id).first()
            if not exec:
                return None
            return _execution_to_model(exec)

    def get_by_file(self, file_id: str) -> List[ExecutionModel]:
        with self.session() as s:
            execs = s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.file_id == file_id
            ).order_by(DBExecution.created_at.desc()).all()
            return [_execution_to_model(e) for e in execs]

    def get_by_user(self, user_id: str, limit: int = 50) -> List[ExecutionModel]:
        with self.session() as s:
            execs = s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.user_id == user_id
            ).order_by(DBExecution.created_at.desc()).limit(limit).all()
            return [_execution_to_model(e) for e in execs]

    def get_pending_executions(self) -> List[ExecutionModel]:
        with self.session() as s:
            execs = s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.status == "pending"
            ).order_by(DBExecution.created_at.asc()).all()
            return [_execution_to_model(e) for e in execs]

    def get_running_executions(self) -> List[ExecutionModel]:
        with self.session() as s:
            execs = s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.status == "running"
            ).all()
            return [_execution_to_model(e) for e in execs]

    def update_status(
        self,
        execution_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> Optional[ExecutionModel]:
        with self.session() as s:
            exec = s.query(DBExecution).filter(DBExecution.id == execution_id).first()
            if not exec:
                return None
            exec.status = status
            if error_message:
                exec.error_message = error_message
            if status == "running":
                exec.started_at = datetime.now(timezone.utc)
            if status in ("completed", "failed", "cancelled"):
                exec.ended_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(exec)
            return _execution_to_model(exec)


class ExecutionNodeRepository(BaseRepository):

    def create(self, data: dict) -> ExecutionNodeModel:
        with self.session() as s:
            node = DBExecutionNode(**data)
            s.add(node)
            s.commit()
            s.refresh(node)
            return _node_to_model(node)

    def get(self, node_id: str) -> Optional[ExecutionNodeModel]:
        with self.session() as s:
            node = s.query(DBExecutionNode).filter(DBExecutionNode.id == node_id).first()
            if not node:
                return None
            return _node_to_model(node)

    def get_by_execution(self, execution_id: str) -> List[ExecutionNodeModel]:
        with self.session() as s:
            nodes = s.query(DBExecutionNode).filter(
                DBExecutionNode.execution_id == execution_id
            ).all()
            return [_node_to_model(n) for n in nodes]

    def update(
        self,
        node_id: str,
        status: Optional[str] = None,
        progress_percent: Optional[int] = None,
        progress_message: Optional[str] = None,
        output_data: Optional[dict] = None,
        container_id: Optional[str] = None,
        cpu_percent: Optional[float] = None,
        memory_mb: Optional[float] = None,
        execution_time_ms: Optional[int] = None,
        error_message: Optional[str] = None,
        logs_path: Optional[str] = None,
    ) -> Optional[ExecutionNodeModel]:
        with self.session() as s:
            node = s.query(DBExecutionNode).filter(DBExecutionNode.id == node_id).first()
            if not node:
                return None
            if status:
                node.status = status
                if status == "running":
                    node.started_at = datetime.now(timezone.utc)
                if status in ("completed", "failed", "skipped"):
                    node.ended_at = datetime.now(timezone.utc)
            if progress_percent is not None:
                node.progress_percent = progress_percent
            if progress_message is not None:
                node.progress_message = progress_message
            if output_data is not None:
                node.output_data = output_data
            if container_id is not None:
                node.container_id = container_id
            if cpu_percent is not None:
                node.cpu_percent = cpu_percent
            if memory_mb is not None:
                node.memory_mb = memory_mb
            if execution_time_ms is not None:
                node.execution_time_ms = execution_time_ms
            if error_message is not None:
                node.error_message = error_message
            if logs_path is not None:
                node.logs_path = logs_path
            s.commit()
            s.refresh(node)
            return _node_to_model(node)
