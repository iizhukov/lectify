from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import joinedload

from src.db.repository.base import BaseRepository
from src.db.entity import DBExecution, DBExecutionNode, ExecutionStatus, NodeExecutionStatus


class ExecutionRepository(BaseRepository):

    def create(self, data: dict) -> DBExecution:
        with self.session() as s:
            execution = DBExecution(**data)
            s.add(execution)
            s.commit()
            s.refresh(execution)
            return execution

    def get(self, execution_id: str) -> Optional[DBExecution]:
        with self.session() as s:
            return s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(DBExecution.id == execution_id).first()

    def get_by_file(self, file_id: str) -> List[DBExecution]:
        with self.session() as s:
            return s.query(DBExecution).filter(
                DBExecution.file_id == file_id
            ).order_by(DBExecution.created_at.desc()).all()

    def get_by_user(self, user_id: str, limit: int = 50) -> List[DBExecution]:
        with self.session() as s:
            return s.query(DBExecution).filter(
                DBExecution.user_id == user_id
            ).order_by(DBExecution.created_at.desc()).limit(limit).all()

    def get_pending_executions(self) -> List[DBExecution]:
        with self.session() as s:
            return s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.status == ExecutionStatus.PENDING
            ).order_by(DBExecution.created_at.asc()).all()

    def get_running_executions(self) -> List[DBExecution]:
        with self.session() as s:
            return s.query(DBExecution).options(
                joinedload(DBExecution.nodes)
            ).filter(
                DBExecution.status == ExecutionStatus.RUNNING
            ).all()

    def update_status(
        self,
        execution_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> Optional[DBExecution]:
        with self.session() as s:
            execution = s.query(DBExecution).filter(DBExecution.id == execution_id).first()
            if not execution:
                return None
            execution.status = status
            if error_message:
                execution.error_message = error_message
            if status == ExecutionStatus.RUNNING:
                execution.started_at = datetime.now(timezone.utc)
            if status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
                execution.ended_at = datetime.now(timezone.utc)
            s.commit()
            s.refresh(execution)
            return execution


class ExecutionNodeRepository(BaseRepository):

    def create(self, data: dict) -> DBExecutionNode:
        with self.session() as s:
            node = DBExecutionNode(**data)
            s.add(node)
            s.commit()
            s.refresh(node)
            return node

    def get(self, node_id: str) -> Optional[DBExecutionNode]:
        with self.session() as s:
            return s.query(DBExecutionNode).filter(DBExecutionNode.id == node_id).first()

    def get_by_execution(self, execution_id: str) -> List[DBExecutionNode]:
        with self.session() as s:
            return s.query(DBExecutionNode).filter(DBExecutionNode.execution_id == execution_id).all()

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
    ) -> Optional[DBExecutionNode]:
        with self.session() as s:
            node = s.query(DBExecutionNode).filter(DBExecutionNode.id == node_id).first()
            if not node:
                return None
            if status:
                node.status = status
                if status == NodeExecutionStatus.RUNNING:
                    node.started_at = datetime.now(timezone.utc)
                if status in [NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED, NodeExecutionStatus.SKIPPED]:
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
            return node
