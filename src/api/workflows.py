"""
Workflow API endpoints
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from src.db.models import WorkflowTemplateModel
from src.db.repository import WorkflowTemplateRepository, ExecutionRepository, ExecutionNodeRepository
from src.workflows.execution import ExecutionEngine

from src.db.entity import ExecutionStatus, NodeExecutionStatus

router = APIRouter(prefix="/api/workflows", tags=["workflows"])
repo = WorkflowTemplateRepository()


def _execution_to_dict(e):
    """
    Serialize DBExecution to dict matching mock contract.
    Mock fields: id, workflow_id, workflow_template_id, file_id, user_id,
                 workflow_name, file_name, language, status, error_message,
                 started_at, ended_at, created_at
    """
    return {
        "id": str(e.id),
        "workflow_id": str(e.workflow_template_id),  # DEPRECATED alias
        "workflow_template_id": str(e.workflow_template_id),
        "file_id": str(e.file_id),
        "user_id": str(e.user_id) if e.user_id else None,
        "workflow_name": e.workflow_template.name if e.workflow_template else None,
        "file_name": getattr(e, "file_name", None),
        "language": getattr(e, "language", "ru"),
        "status": str(e.status),
        "error_message": e.error_message,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "ended_at": e.ended_at.isoformat() if e.ended_at else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _node_to_dict(n):
    """
    Serialize DBExecutionNode to dict matching mock contract.
    Mock fields: id, execution_id, node_id, node_template_id, node_name,
                 status, progress_percent, progress_message,
                 input_data, output_data, container_id, cpu_percent,
                 memory_mb, execution_time_ms, error_message, logs_path,
                 started_at, ended_at
    """
    return {
        "id": str(n.id),
        "execution_id": str(n.execution_id),
        "node_id": str(n.node_id),
        "node_template_id": str(n.node_template_id) if n.node_template_id else None,
        "node_name": getattr(n, "node_name", ""),
        "status": str(n.status),
        "progress_percent": n.progress_percent or 0,
        "progress_message": n.progress_message,
        "input_data": getattr(n, "input_data", None),
        "output_data": getattr(n, "output_data", None),
        "container_id": n.container_id,
        "cpu_percent": n.cpu_percent,
        "memory_mb": n.memory_mb,
        "execution_time_ms": n.execution_time_ms,
        "error_message": n.error_message,
        "logs_path": n.logs_path,
        "started_at": n.started_at.isoformat() if n.started_at else None,
        "ended_at": n.ended_at.isoformat() if n.ended_at else None,
    }


# =============================================
# REQUEST/RESPONSE MODELS
# =============================================

class CreateWorkflowRequest(BaseModel):
    name: str
    description: Optional[str] = None
    nodes: List[dict] = []
    edges: List[dict] = []


class UpdateWorkflowRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    nodes: Optional[List[dict]] = None
    edges: Optional[List[dict]] = None


class ExecuteWorkflowRequest(BaseModel):
    file_id: str
    file_path: str
    language: str = "ru"


# =============================================
# WORKFLOW CRUD
# =============================================

@router.get("", response_model=List[WorkflowTemplateModel])
async def list_workflows(user_id: Optional[str] = None):
    """
    List all workflows (public + user's).

    MIGRATED: use WorkflowTemplateRepository / WorkflowRepository
    DEPRECATED: Repository.get_by_user() / get_public() — migrate to new repos
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.get_by_user() / get_public()"
    )

    # OLD:
    # if user_id:
    #     user_workflows = repo.get_by_user(user_id)
    #     public_workflows = repo.get_public()
    #     workflows = public_workflows + user_workflows
    # else:
    #     workflows = repo.get_public()
    # return [
    #     WorkflowTemplateModel(
    #         id=w.id, user_id=w.user_id, name=w.name,
    #         description=w.description, graph=w.graph,
    #         is_public=w.is_public, created_at=w.created_at,
    #         updated_at=w.updated_at
    #     )
    #     for w in workflows
    # ]


@router.get("/{workflow_id}", response_model=WorkflowTemplateModel)
async def get_workflow(workflow_id: str):
    """
    Get workflow by ID.

    MIGRATED: use WorkflowTemplateRepository.get()
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.get(workflow_id)"
    )

    # OLD:
    # workflow = repo.get(workflow_id)
    # if not workflow:
    #     raise HTTPException(status_code=404, detail="Workflow not found")
    # return WorkflowTemplateModel(
    #     id=workflow.id, user_id=workflow.user_id, name=workflow.name,
    #     description=workflow.description, graph=workflow.graph,
    #     is_public=workflow.is_public, created_at=workflow.created_at,
    #     updated_at=workflow.updated_at
    # )


@router.post("", response_model=WorkflowTemplateModel)
async def create_workflow(
    request: CreateWorkflowRequest,
    user_id: Optional[str] = None
):
    """
    Create a new workflow.

    MIGRATED: use WorkflowTemplateRepository.create()
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.create(data)"
    )

    # OLD:
    # workflow_id = str(uuid.uuid4())
    # graph = {"nodes": request.nodes, "edges": request.edges}
    # workflow = repo.create({
    #     "id": workflow_id, "user_id": user_id, "name": request.name,
    #     "description": request.description, "graph": graph, "is_public": False
    # })
    # return WorkflowTemplateModel(
    #     id=workflow.id, user_id=workflow.user_id, name=workflow.name,
    #     description=workflow.description, graph=workflow.graph,
    #     is_public=workflow.is_public, created_at=workflow.created_at,
    #     updated_at=workflow.updated_at
    # )


@router.put("/{workflow_id}", response_model=WorkflowTemplateModel)
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest
):
    """
    Update a workflow.

    MIGRATED: use WorkflowTemplateRepository.update(workflow_id, **data)
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.update(workflow_id, **data)"
    )

    # OLD:
    # update_data = {}
    # if request.name is not None:
    #     update_data["name"] = request.name
    # if request.description is not None:
    #     update_data["description"] = request.description
    # if request.nodes is not None or request.edges is not None:
    #     existing = repo.get(workflow_id)
    #     if not existing:
    #         raise HTTPException(status_code=404, detail="Workflow not found")
    #     nodes = request.nodes if request.nodes is not None else existing.graph.get("nodes", [])
    #     edges = request.edges if request.edges is not None else existing.graph.get("edges", [])
    #     update_data["graph"] = {"nodes": nodes, "edges": edges}
    # workflow = repo.update(workflow_id, **update_data)
    # if not workflow:
    #     raise HTTPException(status_code=404, detail="Workflow not found")
    # return WorkflowTemplateModel(
    #     id=workflow.id, user_id=workflow.user_id, name=workflow.name,
    #     description=workflow.description, graph=workflow.graph,
    #     is_public=workflow.is_public, created_at=workflow.created_at,
    #     updated_at=workflow.updated_at
    # )


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """
    Delete a workflow.

    MIGRATED: use WorkflowTemplateRepository.delete(workflow_id)
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.delete(workflow_id)"
    )

    # OLD:
    # success = repo.delete(workflow_id)
    # if not success:
    #     raise HTTPException(status_code=404, detail="Workflow not found")
    # return {"status": "ok"}


# =============================================
# PUBLISH / FORK
# =============================================

@router.post("/{workflow_id}/publish")
async def publish_workflow(workflow_id: str):
    """
    Publish a workflow (make it public).

    MIGRATED: use WorkflowTemplateRepository.update(workflow_id, is_public=True)
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.update(workflow_id, is_public=True)"
    )

    # OLD:
    # workflow = repo.update(workflow_id, is_public=True)
    # if not workflow:
    #     raise HTTPException(status_code=404, detail="Workflow not found")
    # public = repo.publish(workflow_id)
    # return {
    #     "workflow_id": workflow.id,
    #     "public_id": public.id if public else None,
    #     "is_public": True
    # }


@router.post("/public/{public_id}/fork")
async def fork_workflow(public_id: str, user_id: str):
    """
    Fork a public workflow to user's private workflows.

    MIGRATED: use WorkflowTemplateRepository.fork(public_id, user_id)
    """
    raise NotImplementedError(
        "MIGRATED: use WorkflowTemplateRepository.fork(public_id, user_id)"
    )

    # OLD:
    # workflow = repo.fork(public_id, user_id)
    # if not workflow:
    #     raise HTTPException(status_code=404, detail="Public workflow not found")
    # return {"workflow_id": workflow.id, "name": workflow.name}


# =============================================
# EXECUTION — ORCHESTRATOR PATH
# =============================================

@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    user_id: Optional[str] = None
):
    """
    Start workflow execution.
    Creates a PENDING execution — OrchestratorService picks it up automatically.

    MIGRATED: ExecutionRepository / ExecutionNodeRepository with updated
    ExecutionModel fields (workflow_name, file_name, language, node_name).
    """
    raise NotImplementedError(
        "MIGRATED: ExecutionRepository + ExecutionNodeRepository; "
        "ExecutionModel now has workflow_name, file_name, language; "
        "ExecutionNodeModel now has node_name"
    )

    # OLD:
    # from src.db.repository import DBRepository, WorkflowTemplateRepository
    # from src.db.entity import DBExecution, DBExecutionNode
    # from datetime import datetime, timezone
    # db_repo = DBRepository()
    # wf_repo = WorkflowTemplateRepository()
    # wf_entity = wf_repo.get(workflow_id)
    # if not wf_entity:
    #     raise HTTPException(status_code=404, detail="Workflow template not found")
    # execution_id = str(uuid.uuid4())
    # with db_repo.session() as s:
    #     execution = DBExecution(
    #         id=execution_id, workflow_template_id=workflow_id,
    #         file_id=request.file_id, user_id=user_id,
    #         status=ExecutionStatus.PENDING,
    #         created_at=datetime.now(timezone.utc),
    #     )
    #     s.add(execution)
    #     graph = wf_entity.graph
    #     for node_def in graph.get("nodes", []):
    #         node_exec = DBExecutionNode(
    #             id=str(uuid.uuid4()), execution_id=execution_id,
    #             node_id=node_def["id"],
    #             node_template_id=node_def.get("template_id"),
    #             status=NodeExecutionStatus.PENDING,
    #             created_at=datetime.now(timezone.utc),
    #             progress_percent=0, progress_message="Ожидание...",
    #         )
    #         s.add(node_exec)
    #     s.commit()
    #     s.refresh(execution)
    # return {
    #     "execution_id": execution_id,
    #     "status": ExecutionStatus.PENDING,
    #     "message": "Execution queued — OrchestratorService will pick it up shortly"
    # }


# =============================================
# EXECUTION STATUS & NODES
# =============================================

@router.get("/executions")
async def list_executions():
    """
    List all executions.

    MIGRATED: use ExecutionRepository with updated ExecutionModel fields.
    """
    raise NotImplementedError(
        "MIGRATED: use ExecutionRepository; _execution_to_dict updated"
    )

    # OLD:
    # from src.db.repository import DBRepository
    # db = DBRepository()
    # try:
    #     all_executions = db.get_pending_executions() + db.get_running_executions()
    # except Exception:
    #     with db.session() as s:
    #         from src.db.entity import DBExecution
    #         all_executions = s.query(DBExecution).all()
    # return [_execution_to_dict(e) for e in all_executions]


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    """
    Get execution by ID.

    MIGRATED: use ExecutionRepository.get(execution_id)
    """
    raise NotImplementedError(
        "MIGRATED: use ExecutionRepository.get(execution_id)"
    )

    # OLD:
    # from src.db.repository import DBRepository
    # db = DBRepository()
    # execution = db.get(execution_id)
    # if not execution:
    #     raise HTTPException(status_code=404, detail="Execution not found")
    # return _execution_to_dict(execution)


@router.get("/executions/{execution_id}/nodes")
async def get_execution_nodes(execution_id: str):
    """
    Get all node executions for an execution.

    MIGRATED: use ExecutionNodeRepository.get_by_execution(execution_id)
    """
    raise NotImplementedError(
        "MIGRATED: use ExecutionNodeRepository.get_by_execution(execution_id); "
        "_node_to_dict updated with node_name, input_data, output_data"
    )

    # OLD:
    # from src.db.repository import DBRepository
    # db = DBRepository()
    # nodes = db.get_by_execution(execution_id)
    # return [_node_to_dict(n) for n in nodes]


# =============================================
# LOGS — READING & STREAMING
# =============================================

@router.get("/executions/{execution_id}/nodes/{node_id}/logs")
async def get_node_logs(execution_id: str, node_id: str):
    """
    Read logs for a node execution.
    First tries MinIO (logs_path), then falls back to live container logs.

    MIGRATED: unchanged — uses ExecutionNodeRepository.get_by_execution()
    """
    raise NotImplementedError(
        "MIGRATED: use ExecutionNodeRepository.get_by_execution(execution_id)"
    )

    # OLD:
    # from src.db.repository import DBRepository
    # from src.utils.storage import get_storage
    # from src.docker.runner import ContainerRunner
    # db = DBRepository()
    # nodes = db.get_by_execution(execution_id)
    # node = next((n for n in nodes if str(n.node_id) == node_id), None)
    # if not node:
    #     raise HTTPException(status_code=404, detail="Node not found")
    # if node.logs_path:
    #     try:
    #         storage = get_storage()
    #         content = storage.read_log(node.logs_path)
    #         return {"source": "minio", "logs": content, "logs_path": node.logs_path}
    #     except Exception:
    #         pass
    # if node.container_id:
    #     try:
    #         runner = ContainerRunner()
    #         logs = runner.docker.get_container_logs(node.container_id)
    #         return {"source": "container", "logs": logs, "container_id": node.container_id}
    #     except Exception:
    #         pass
    # return {
    #     "source": "none",
    #     "logs": node.progress_message or "No logs available yet",
    #     "logs_path": node.logs_path
    # }


@router.get("/executions/{execution_id}/nodes/{node_id}/logs/stream")
async def stream_node_logs(execution_id: str, node_id: str):
    """
    SSE stream for live node logs.
    Polls MinIO path every 2 seconds until logs appear.

    MIGRATED: unchanged — uses ExecutionNodeRepository.get_by_execution()
    """
    raise NotImplementedError(
        "MIGRATED: SSE stream; uses ExecutionNodeRepository.get_by_execution()"
    )

    # OLD:
    # from fastapi.responses import StreamingResponse
    # from src.db.repository import DBRepository
    # from src.utils.storage import get_storage
    # import asyncio
    # db = DBRepository()
    # async def event_generator():
    #     checked_paths = set()
    #     for _ in range(60):
    #         nodes = db.get_by_execution(execution_id)
    #         node = next((n for n in nodes if str(n.node_id) == node_id), None)
    #         if not node:
    #             yield "data: {\"error\": \"node not found\"}\n\n"
    #             break
    #         if node.logs_path and str(node.logs_path) not in checked_paths:
    #             try:
    #                 storage = get_storage()
    #                 content = storage.read_log(str(node.logs_path))
    #                 if content:
    #                     checked_paths.add(str(node.logs_path))
    #                     yield f"data: {content}\n\n"
    #             except Exception:
    #                 pass
    #         if node.status in [NodeExecutionStatus.COMPLETED, NodeExecutionStatus.FAILED]:
    #             yield "data: [DONE]\n\n"
    #             break
    #         yield "data: \n\n"
    #         await asyncio.sleep(2)
    # return StreamingResponse(
    #     event_generator(),
    #     media_type="text/event-stream",
    #     headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    # )


# =============================================
# WEBSOCKET FOR REAL-TIME UPDATES
# =============================================

class ExecutionWebSocket:
    """WebSocket manager for execution updates"""

    def __init__(self):
        self.connections: dict = {}

    async def connect(self, execution_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[execution_id] = websocket

    def disconnect(self, execution_id: str):
        self.connections.pop(execution_id, None)

    async def send_progress(self, execution_id: str, data: dict):
        if execution_id in self.connections:
            await self.connections[execution_id].send_json(data)


ws_manager = ExecutionWebSocket()


@router.websocket("/ws/executions/{execution_id}")
async def execution_websocket(websocket: WebSocket, execution_id: str):
    """
    WebSocket for real-time execution updates.

    MIGRATED: unchanged — uses ExecutionRepository.get() / .nodes
    """
    raise NotImplementedError(
        "MIGRATED: ExecutionRepository.get(); WebSocket SSE format unchanged"
    )

    # OLD:
    # await ws_manager.connect(execution_id, websocket)
    # try:
    #     from src.db.repository import DBRepository
    #     db = DBRepository()
    #     engine = ExecutionEngine()
    #     execution = db.get(execution_id)
    #     if execution:
    #         await websocket.send_json({
    #             "type": "execution_status",
    #             "execution_id": execution_id,
    #             "status": str(execution.status)
    #         })
    #     while True:
    #         execution = db.get(execution_id)
    #         if execution:
    #             await websocket.send_json({
    #                 "type": "execution_status",
    #                 "execution_id": execution_id,
    #                 "status": execution.status,
    #                 "nodes": [
    #                     {"node_id": n.node_id, "status": n.status,
    #                      "progress_percent": n.progress_percent,
    #                      "progress_message": n.progress_message}
    #                     for n in (execution.nodes or [])
    #                 ]
    #             })
    #         if execution and execution.status in ["completed", "failed", "cancelled"]:
    #             break
    #         import asyncio
    #         await asyncio.sleep(1)
    # except WebSocketDisconnect:
    #     ws_manager.disconnect(execution_id)
