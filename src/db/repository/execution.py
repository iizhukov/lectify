from datetime import datetime, timezone
from typing import Optional, List, cast

from sqlalchemy.orm import joinedload

from src.db.repository.base import BaseRepository
from src.db.entity import DBExecution, DBExecutionNode
from src.db.models.execution import ExecutionModel, ExecutionNodeModel, NodeExecutionStatus, ExecutionStatus
from src.db.models.workflow_template import WorkflowTemplateModel, WorkflowGraph


def _node_to_model(node: DBExecutionNode) -> ExecutionNodeModel:
    def _dt(v):
        return v.isoformat() if v else None

    duration_str = None
    execution_time_ms = cast(Optional[int], node.execution_time_ms)
    if execution_time_ms is not None:
        total_s = int(execution_time_ms) / 1000
        h, rem = divmod(int(total_s), 3600)
        m, s = divmod(rem, 60)
        duration_str = f"{h:02d}:{m:02d}:{s:02d}"

    avg_cpu = None
    cpu_percent = cast(Optional[float], node.cpu_percent)
    if cpu_percent is not None:
        avg_cpu = cpu_percent

    return ExecutionNodeModel(
        id=cast(str, node.id),
        execution_id=cast(str, node.execution_id),
        node_template_id=cast(Optional[str], node.node_template_id),
        node_id=cast(str, node.node_id),
        plugin_id=cast(Optional[str], node.plugin_id),
        node_name=cast(str, node.node_name) or "",
        status=NodeExecutionStatus(node.status),
        progress_percent=cast(Optional[int], node.progress_percent),
        progress_message=cast(Optional[str], node.progress_message),
        input_data=cast(Optional[dict], node.input_data),
        output_data=cast(Optional[dict], node.output_data),
        container_id=cast(Optional[str], node.container_id),
        cpu_percent=cpu_percent,
        avg_cpu_percent=avg_cpu,
        memory_mb=cast(Optional[float], node.memory_mb),
        execution_time_ms=execution_time_ms,
        duration_str=duration_str,
        error_message=cast(Optional[str], node.error_message),
        logs_path=cast(Optional[str], node.logs_path),
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
        wt: WorkflowTemplateModel = exec.workflow_template
        workflow_template = WorkflowTemplateModel(
            id=cast(str, wt.id),
            user_id=cast(Optional[str], wt.user_id),
            name=cast(str, wt.name) or "",
            description=cast(Optional[str], wt.description),
            graph=WorkflowGraph.model_validate(cast(dict, wt.graph)),
            is_public=cast(bool, wt.is_public) or False,
            created_at=_dt(wt.created_at),
            updated_at=_dt(wt.updated_at) if hasattr(wt, 'updated_at') else None,
        )

    input_files_val = cast(Optional[dict], exec.input_files)

    return ExecutionModel(
        id=str(exec.id),
        workflow_template_id=str(exec.workflow_template_id),
        file_id=str(exec.file_id),
        user_id=str(exec.user_id),
        workflow_name=str(exec.workflow_name),
        file_name=str(exec.file_name),
        language=str(exec.language) or "ru",
        input_files=dict(input_files_val) if input_files_val else {},
        status=ExecutionStatus(cast(str, exec.status)),
        started_at=_dt(exec.started_at),
        ended_at=_dt(exec.ended_at),
        error_message=str(exec.error_message),
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

            if error_message is not None:
                exec.error_message = error_message if error_message else None

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
        input_data: Optional[dict] = None,
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

            if input_data is not None:
                node.input_data = input_data

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
