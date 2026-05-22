from datetime import datetime
from sqlalchemy.orm import Session
from typing import List, Optional

from src.db.database import SessionLocal, DBFile, DBWorkflowNode, DBWorkflow
from src.db.models import FileModel, WorkflowNodeModel, WorkflowStateModel, NodeStatus


class DBRepository:
    def __init__(self):
        self.Session = SessionLocal

    def create_file(self, file_id: str, filename: str, language: str) -> FileModel:
        with self.Session() as session:
            db_file = DBFile(id=file_id, filename=filename, language=language, status="pending")

            session.add(db_file)
            session.commit()
            session.refresh(db_file)

            return FileModel.model_validate(db_file)

    def create_workflow(self, workflow_id: str, file_id: str, name: str) -> WorkflowStateModel:
        with self.Session() as session:
            db_wf = DBWorkflow(
                id=workflow_id,
                file_id=file_id,
                name=name,
                status=NodeStatus.PENDING,
            )

            session.add(db_wf)
            session.commit()
            session.refresh(db_wf)

            return WorkflowStateModel.model_validate(db_wf)

    def update_workflow(self, workflow_id: str, status: NodeStatus, final_artifact_path: Optional[str] = None) -> WorkflowStateModel:
        with self.Session() as session:
            db_wf = session.query(DBWorkflow).filter_by(id=workflow_id).first()
            if not db_wf:
                raise ValueError(f"Workflow {workflow_id} not found.")
            
            db_wf.status = status
            if final_artifact_path:
                db_wf.final_artifact_path = final_artifact_path
            
            if status in [NodeStatus.COMPLETED, NodeStatus.FAILED]:
                db_wf.ended_at = datetime.now().isoformat()
                
            session.commit()
            session.refresh(db_wf)

            return WorkflowStateModel.model_validate(db_wf)

    def get_workflow_details(self, workflow_id: str) -> Optional[WorkflowStateModel]:
        with self.Session() as session:
            db_wf = session.query(DBWorkflow).filter_by(id=workflow_id).first()

            if not db_wf:
                return None

            return WorkflowStateModel.model_validate(db_wf)

    def get_all_workflows(self) -> List[WorkflowStateModel]:
        with self.Session() as session:
            db_wfs = session.query(DBWorkflow).order_by(DBWorkflow.created_at.desc()).all()
            return [WorkflowStateModel.model_validate(w) for w in db_wfs]

    def create_workflow_nodes(self, file_id: str, nodes: List[dict]):
        with self.Session() as session:
            for node_data in nodes:
                db_node = DBWorkflowNode(
                    file_id=file_id,
                    node_id=node_data["node_id"],
                    node_name=node_data["node_name"],
                    status="pending",
                    message="Ожидание запуска..."
                )
                session.add(db_node)

            session.commit()

    def update_node(self, file_id: str, node_id: str, status: str, message: Optional[str] = None, artifact_path: Optional[str] = None) -> WorkflowNodeModel:
        with self.Session() as session:
            db_node = session.query(DBWorkflowNode).filter_by(file_id=file_id, node_id=node_id).first()
            if not db_node:
                raise ValueError(f"Node {node_id} for file {file_id} not found.")

            now = datetime.now().isoformat()
            db_node.status = status
            
            if message is not None:
                db_node.message = message
            if artifact_path is not None:
                db_node.artifact_path = artifact_path

            if status == "running":
                db_node.started_at = now
            elif status in ["completed", "failed"]:
                db_node.ended_at = now

            session.commit()
            session.refresh(db_node)

            self._update_file_overall_status(session, file_id)
            return WorkflowNodeModel.model_validate(db_node)

    def _update_file_overall_status(self, session: Session, file_id: str):
        db_file = session.query(DBFile).filter_by(id=file_id).first()
        if not db_file:
            return

        node_statuses = [node.status for node in db_file.nodes]
        
        overall = "processing"
        if all(s == "completed" for s in node_statuses):
            overall = "completed"
        elif any(s == "failed" for s in node_statuses):
            overall = "failed"
        elif all(s == "pending" for s in node_statuses):
            overall = "pending"

        db_file.status = overall
        session.commit()

    def get_all_files(self) -> List[FileModel]:
        with self.Session() as session:
            db_files = session.query(DBFile).order_by(DBFile.created_at.desc()).all()
            return [FileModel.model_validate(f) for f in db_files]

    def get_file_details(self, file_id: str) -> Optional[FileModel]:
        with self.Session() as session:
            db_file = session.query(DBFile).filter_by(id=file_id).first()
            if not db_file:
                return None
            return FileModel.model_validate(db_file)

    def get_interrupted_files(self) -> List[dict]:
        with self.Session() as session:
            unfinished_nodes = session.query(DBWorkflowNode).filter(DBWorkflowNode.status.in_(["running", "pending"])).all()
            interrupted = []
            seen_ids = set()

            for node in unfinished_nodes:
                if node.file_id not in seen_ids:
                    seen_ids.add(node.file_id)
                    db_file = session.query(DBFile).filter_by(id=node.file_id).first()

                    if db_file:
                        interrupted.append({
                            "id": db_file.id,
                            "filename": db_file.filename,
                            "language": db_file.language
                        })

            return interrupted
