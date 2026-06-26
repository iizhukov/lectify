import os
import uuid

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import joinedload

from src.db.repository.base import BaseRepository
from src.db.entity import (
    DBFile,
    DBWorkflow,
    DBWorkflowNode,
    DBArtifact,
    DBWorkflowNodeDependency
)
from src.db.models import (
    FileModel,
    WorkflowStateModel,
    WorkflowNodeModel,
    WorkflowEdgeModel,
    WorkflowGraphModel,
    ArtifactModel,
    FileStatus,
    NodeStatus
)


class WorkflowRepository(BaseRepository):
    """Repository for files, workflows, nodes and artifacts"""

    # =========================================================
    # FILES
    # =========================================================

    def create_file(
        self,
        file_id: str,
        filename: str,
        original_path: str,
        language: str,
        size_bytes: int,
        mime_type: str,
        minio_path: Optional[str] = None
    ) -> FileModel:
        with self.session() as s:
            db_file = DBFile(
                id=file_id,
                filename=filename,
                original_path=original_path,
                language=language,
                status=FileStatus.PENDING,
                size_bytes=size_bytes,
                mime_type=mime_type,
                minio_path=minio_path
            )
            s.add(db_file)
            s.commit()
            s.refresh(db_file)
            return FileModel.model_validate(db_file)

    def get_all_files(self) -> List[FileModel]:
        with self.session() as s:
            files = (
                s.query(DBFile)
                .options(joinedload(DBFile.workflows))
                .order_by(DBFile.created_at.desc())
                .all()
            )
            return [FileModel.model_validate(x) for x in files]

    def get_file_details(self, file_id: str) -> Optional[FileModel]:
        with self.session() as s:
            db_file = (
                s.query(DBFile)
                .options(
                    joinedload(DBFile.workflows)
                    .joinedload(DBWorkflow.nodes)
                    .joinedload(DBWorkflowNode.artifacts)
                )
                .filter(DBFile.id == file_id)
                .first()
            )
            if not db_file:
                return None
            return FileModel.model_validate(db_file)

    def update_file_status(self, file_id: str, status: FileStatus):
        with self.session() as s:
            db_file = s.query(DBFile).filter(DBFile.id == file_id).first()
            if db_file:
                db_file.status = status
                s.commit()

    # =========================================================
    # WORKFLOWS
    # =========================================================

    def create_workflow(
        self,
        workflow_id: str,
        file_id: str,
        name: str
    ) -> WorkflowStateModel:
        with self.session() as s:
            db_wf = DBWorkflow(
                id=workflow_id,
                file_id=file_id,
                name=name,
                status=NodeStatus.PENDING
            )
            s.add(db_wf)
            s.commit()
            s.refresh(db_wf)
            return WorkflowStateModel.model_validate(db_wf)

    def update_workflow_status(
        self,
        workflow_id: str,
        status: NodeStatus,
        final_artifact_id: Optional[str] = None
    ):
        with self.session() as s:
            wf = s.query(DBWorkflow).filter(DBWorkflow.id == workflow_id).first()
            if wf:
                wf.status = status
                if status == NodeStatus.RUNNING:
                    wf.started_at = datetime.now(timezone.utc)
                if status in [NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.CANCELLED]:
                    wf.ended_at = datetime.now(timezone.utc)
                if final_artifact_id:
                    wf.final_artifact_id = final_artifact_id
                s.commit()

    def get_workflow_details(self, workflow_id: str) -> Optional[WorkflowStateModel]:
        with self.session() as s:
            wf = (
                s.query(DBWorkflow)
                .options(
                    joinedload(DBWorkflow.nodes)
                    .joinedload(DBWorkflowNode.artifacts)
                )
                .filter(DBWorkflow.id == workflow_id)
                .first()
            )
            if not wf:
                return None

            nodes = []
            for node in wf.nodes:
                deps = [x.dependency_node_id for x in node.dependencies]
                nodes.append(
                    WorkflowNodeModel(
                        id=node.id,
                        workflow_id=node.workflow_id,
                        file_id=node.file_id,
                        node_id=node.node_id,
                        node_name=node.node_name,
                        status=node.status,
                        message=node.message,
                        artifact_path=node.artifact_path,
                        started_at=node.started_at,
                        ended_at=node.ended_at,
                        artifacts=node.artifacts,
                        dependencies=deps
                    )
                )

            edges = []
            for node in nodes:
                for dep in node.dependencies:
                    edges.append(
                        WorkflowEdgeModel(from_node_id=dep, to_node_id=node.node_id)
                    )

            return WorkflowStateModel(
                id=wf.id,
                file_id=wf.file_id,
                name=wf.name,
                status=wf.status,
                created_at=wf.created_at,
                started_at=wf.started_at,
                ended_at=wf.ended_at,
                final_artifact_id=wf.final_artifact_id,
                graph=WorkflowGraphModel(nodes=nodes, edges=edges)
            )

    def get_all_workflows(self) -> List[WorkflowStateModel]:
        with self.session() as s:
            workflows = s.query(DBWorkflow).order_by(DBWorkflow.created_at.desc()).all()
            return [WorkflowStateModel.model_validate(x) for x in workflows]

    # =========================================================
    # NODES
    # =========================================================

    def create_workflow_nodes(self, workflow_id: str, file_id: str, nodes: List[dict]):
        with self.session() as s:
            for node_data in nodes:
                db_node = DBWorkflowNode(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    file_id=file_id,
                    node_id=node_data["node_id"],
                    node_name=node_data["node_name"],
                    status=NodeStatus.PENDING,
                    message="Waiting..."
                )
                s.add(db_node)
                s.flush()

                for dep in node_data.get("dependencies", []):
                    s.add(
                        DBWorkflowNodeDependency(
                            id=str(uuid.uuid4()),
                            node_db_id=db_node.id,
                            dependency_node_id=dep
                        )
                    )
            s.commit()

    def update_node(
        self,
        workflow_id: str,
        node_id: str,
        status: NodeStatus,
        message: Optional[str] = None,
        artifact_path: Optional[str] = None
    ):
        with self.session() as s:
            node = (
                s.query(DBWorkflowNode)
                .filter(
                    DBWorkflowNode.workflow_id == workflow_id,
                    DBWorkflowNode.node_id == node_id
                )
                .first()
            )
            if node:
                node.status = status
                if message is not None:
                    node.message = message
                if artifact_path is not None:
                    node.artifact_path = artifact_path
                if status == NodeStatus.RUNNING:
                    node.started_at = datetime.now(timezone.utc)
                if status in [NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.CANCELLED]:
                    node.ended_at = datetime.now(timezone.utc)
                s.commit()

    # =========================================================
    # ARTIFACTS
    # =========================================================

    def create_artifact(
        self,
        workflow_id: str,
        file_id: str,
        node_id: str,
        path: str,
        minio_path: str = None
    ) -> ArtifactModel:
        with self.session() as s:
            node = (
                s.query(DBWorkflowNode)
                .filter(
                    DBWorkflowNode.workflow_id == workflow_id,
                    DBWorkflowNode.node_id == node_id
                )
                .first()
            )
            if not node:
                raise ValueError("Node not found")

            p = os.path.abspath(path)
            artifact = DBArtifact(
                id=str(uuid.uuid4()),
                file_id=file_id,
                workflow_id=workflow_id,
                node_id=node.id,
                name=os.path.basename(p),
                ext=os.path.splitext(p)[1].replace(".", ""),
                mime_type="application/octet-stream",
                path=p,
                minio_path=minio_path,
                size_bytes=os.path.getsize(p)
            )
            s.add(artifact)
            s.commit()
            s.refresh(artifact)
            return ArtifactModel.model_validate(artifact)

    def get_artifact(self, artifact_id: str) -> Optional[ArtifactModel]:
        with self.session() as s:
            artifact = s.query(DBArtifact).filter(DBArtifact.id == artifact_id).first()
            if not artifact:
                return None
            return ArtifactModel.model_validate(artifact)

    def get_interrupted_files(self) -> List[FileModel]:
        with self.session() as s:
            files = (
                s.query(DBFile)
                .join(DBWorkflow)
                .filter(
                    DBWorkflow.status.in_([NodeStatus.RUNNING, NodeStatus.PENDING])
                )
                .all()
            )
            return [FileModel.model_validate(x) for x in files]
