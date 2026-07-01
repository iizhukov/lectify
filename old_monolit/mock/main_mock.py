"""
Mock backend for frontend development
Serves HTML templates + mock API endpoints with full auth support
"""

import pathlib
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Header, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from mock.mock_data import (
    MOCK_USERS,
    MOCK_PASSWORD_HASH,
    MOCK_RESET_TOKENS,
    MOCK_SESSIONS,
    MOCK_WORKFLOWS,
    MOCK_EXECUTIONS,
    MOCK_EXECUTION_NODES,
    MOCK_FILES,
    MOCK_ARTIFACTS,
    MOCK_NODE_TEMPLATES,
    MOCK_PROMPTS,
    MOCK_PLUGINS,
    MOCK_QUEUE_STATUS,
    MOCK_NODE_LOGS,
)


# =============================================
# PATHS
# =============================================

HTML_PATH = pathlib.Path(__file__).parent.parent / "resources" / "templates"
JINJA = Environment(loader=FileSystemLoader(str(HTML_PATH)), autoescape=True)
STATIC_PATH = pathlib.Path(__file__).parent.parent / "resources" / "static"


# =============================================
# APP SETUP
# =============================================

app = FastAPI(title="Lectify Mock Backend")

app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")


# =============================================
# HTML HELPERS
# =============================================

def read_html(filename: str):
    path = HTML_PATH / filename
    if not path.exists():
        return HTMLResponse(f"<h3>Error: {filename} not found!</h3>", status_code=404)
    content = path.read_text(encoding="utf-8")
    if "{% extends" in content or "{% block" in content:
        return HTMLResponse(JINJA.get_template(filename).render())
    return HTMLResponse(content)


# =============================================
# WEB ROUTES (HTML rendering)
# =============================================

web_router = APIRouter()


@web_router.get("/")
async def index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/executions", status_code=302)


@web_router.get("/register")
async def register_page():
    return read_html("register.html")


@web_router.get("/login")
async def login_page():
    return read_html("login.html")


@web_router.get("/forgot-password")
async def forgot_password_page():
    return read_html("forgot-password.html")


@web_router.get("/reset-password")
async def reset_password_page(token: str = Query(None)):
    return read_html("reset-password.html")


@web_router.get("/profile")
async def profile_page():
    return read_html("profile.html")


@web_router.get("/workflows/{workflow_id}")
async def workflow_edit(workflow_id: str):
    return read_html("workflow-edit.html")


@web_router.get("/workflows")
async def workflows():
    return read_html("workflows.html")


@web_router.get("/executions")
async def executions():
    return read_html("executions.html")


@web_router.get("/executions/{execution_id}")
async def execution_detail(execution_id: str):
    return read_html("execution-detail.html")


@web_router.get("/prompts")
async def prompts():
    return read_html("prompts.html")


@web_router.get("/files/{file_id}")
async def file_details(file_id: str):
    return read_html("file_details.html")


app.include_router(web_router)


# =============================================
# AUTH HELPERS
# =============================================

def create_token(user_id: str) -> str:
    token = f"mock-token-{uuid.uuid4().hex}"
    MOCK_SESSIONS[token] = {
        "user_id": user_id,
        "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat()
    }
    return token


def verify_token(authorization: str = Header(None)) -> Optional[str]:
    """Returns user_id if token is valid, None otherwise"""
    if not authorization:
        return None

    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization

    session = MOCK_SESSIONS.get(token)
    if not session:
        return None

    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at < datetime.utcnow():
        del MOCK_SESSIONS[token]
        return None

    return session["user_id"]


def require_auth(authorization: str = Header(None)) -> str:
    """Returns user_id or raises 401"""
    user_id = verify_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


# =============================================
# REQUEST/RESPONSE MODELS
# =============================================

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None


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


class CreateNodeRequest(BaseModel):
    plugin_id: str
    name: str
    description: Optional[str] = None
    parameters: dict = {}
    input_mapping: Optional[List[dict]] = None
    prompt_id: Optional[str] = None


class UpdateNodeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parameters: Optional[dict] = None
    input_mapping: Optional[List[dict]] = None
    prompt_id: Optional[str] = None


class CreatePromptRequest(BaseModel):
    name: str
    system_prompt: Optional[str] = None
    user_prompt_template: str
    variables: Optional[List[str]] = None


class UpdatePromptRequest(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    variables: Optional[List[str]] = None


# =============================================
# AUTH API
# =============================================

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register")
async def register(request: RegisterRequest):
    for user in MOCK_USERS:
        if user["username"] == request.username:
            raise HTTPException(status_code=400, detail="Username already taken")
        if user["email"] == request.email:
            raise HTTPException(status_code=400, detail="Email already registered")
    new_user = {
        "id": f"user-{uuid.uuid4().hex[:8]}",
        "username": request.username,
        "email": request.email,
        "full_name": request.full_name or request.username,
        "avatar_url": None,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    MOCK_USERS.append(new_user)
    token = create_token(new_user["id"])
    return {"token": token, "user_id": new_user["id"], "username": new_user["username"]}


@auth_router.post("/login")
async def login(request: LoginRequest):
    """Login with username/password"""
    for user in MOCK_USERS:
        if user["username"] == request.username:
            # In real app, verify password hash
            if request.password == "password123":  # Mock password check
                token = create_token(user["id"])
                return {
                    "token": token,
                    "user_id": user["id"],
                    "username": user["username"]
                }
            else:
                raise HTTPException(status_code=401, detail="Invalid credentials")

    raise HTTPException(status_code=401, detail="Invalid credentials")


@auth_router.post("/logout")
async def logout(authorization: str = Header(None)):
    """Logout - invalidate token"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if token in MOCK_SESSIONS:
            del MOCK_SESSIONS[token]
    return {"status": "ok"}


@auth_router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Request password reset"""
    # Always return success to not reveal if email exists
    return {"message": "If the email exists, a reset link has been sent"}


@auth_router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password with token"""
    token_data = MOCK_RESET_TOKENS.get(request.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    expires_at = datetime.fromisoformat(token_data["expires_at"])
    if expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Token expired")

    # In real app, update user password hash
    del MOCK_RESET_TOKENS[request.token]
    return {"status": "ok"}


@auth_router.post("/refresh")
async def refresh_token(authorization: str = Header(None)):
    """Refresh access token"""
    user_id = require_auth(authorization)
    token = create_token(user_id)
    return {"token": token}


app.include_router(auth_router)


# =============================================
# PROFILE API
# =============================================

profile_router = APIRouter(prefix="/api/profile", tags=["profile"])


@profile_router.get("")
async def get_profile(authorization: str = Header(None)):
    """Get current user profile"""
    user_id = require_auth(authorization)

    for user in MOCK_USERS:
        if user["id"] == user_id:
            return user

    raise HTTPException(status_code=404, detail="User not found")


@profile_router.put("")
async def update_profile(
    request: UpdateProfileRequest,
    authorization: str = Header(None)
):
    """Update profile (full_name, avatar_url)"""
    user_id = require_auth(authorization)

    for user in MOCK_USERS:
        if user["id"] == user_id:
            if request.full_name is not None:
                user["full_name"] = request.full_name
            if request.avatar_url is not None:
                user["avatar_url"] = request.avatar_url
            user["updated_at"] = datetime.utcnow().isoformat() + "Z"
            return user

    raise HTTPException(status_code=404, detail="User not found")


@profile_router.put("/password")
async def change_password(
    request: ChangePasswordRequest,
    authorization: str = Header(None)
):
    """Change password"""
    user_id = require_auth(authorization)

    # In real app, verify current password and update hash
    if request.current_password != "password123":
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    return {"status": "ok"}


app.include_router(profile_router)


# =============================================
# WORKFLOW API
# =============================================

workflows_router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@workflows_router.get("", response_model=List[dict])
async def list_workflows(
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """List all workflows (public + user's)"""
    current_user = verify_token(authorization)

    if user_id or current_user:
        user_wfs = [w for w in MOCK_WORKFLOWS if w.get("user_id") in [user_id, current_user]]
        public_wfs = [w for w in MOCK_WORKFLOWS if w.get("is_public")]
        return user_wfs + public_wfs

    return [w for w in MOCK_WORKFLOWS if w.get("is_public")]


# Execution routes — MUST be before /{workflow_id} catch-all
@workflows_router.get("/executions", response_model=List[dict])
async def list_executions(
    status: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """List all executions"""
    executions = MOCK_EXECUTIONS
    if status:
        executions = [e for e in executions if e["status"] == status]
    return executions


@workflows_router.get("/executions/{execution_id}", response_model=dict)
async def get_execution(execution_id: str):
    """Get execution by ID"""
    for e in MOCK_EXECUTIONS:
        if e["id"] == execution_id:
            result = dict(e)
            wf = next((w for w in MOCK_WORKFLOWS if w["id"] == e.get("workflow_id")), None)
            if wf and "graph" in wf:
                result["workflow_graph"] = wf["graph"]
            return result
    raise HTTPException(status_code=404, detail="Execution not found")


@workflows_router.get("/executions/{execution_id}/nodes", response_model=List[dict])
async def get_execution_nodes(execution_id: str):
    """Get all nodes for an execution"""
    return MOCK_EXECUTION_NODES.get(execution_id, [])


@workflows_router.get("/executions/{execution_id}/nodes/{node_id}", response_model=dict)
async def get_node_detail(execution_id: str, node_id: str):
    """Get a specific node detail"""
    nodes = MOCK_EXECUTION_NODES.get(execution_id, [])
    for n in nodes:
        if n["id"] == node_id or n["node_id"] == node_id:
            return n
    raise HTTPException(status_code=404, detail="Node not found")


@workflows_router.get("/executions/{execution_id}/nodes/{node_id}/logs")
async def get_node_logs(execution_id: str, node_id: str):
    """Get node logs"""
    from mock.mock_data import MOCK_NODE_LOGS
    _ = MOCK_NODE_LOGS.get(node_id, "")
    return {"attempt": 1, "url": f"http://localhost:9000/mock-logs/{execution_id}/{node_id}/node.log"}


@workflows_router.get("/executions/{execution_id}/artifacts", response_model=List[dict])
async def list_execution_artifacts(execution_id: str):
    """List all artifacts for an execution"""
    return [a for a in MOCK_ARTIFACTS if a.get("workflow_id") == execution_id]


@workflows_router.get("/{workflow_id}", response_model=dict)
async def get_workflow(workflow_id: str):
    """Get workflow by ID"""
    for w in MOCK_WORKFLOWS:
        if w["id"] == workflow_id:
            return w
    raise HTTPException(status_code=404, detail="Workflow not found")


@workflows_router.post("", response_model=dict)
async def create_workflow(
    request: CreateWorkflowRequest,
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """Create a new workflow"""
    current_user = verify_token(authorization) or user_id

    workflow = {
        "id": f"wf-{uuid.uuid4().hex[:8]}",
        "user_id": current_user,
        "name": request.name,
        "description": request.description,
        "graph": {"nodes": request.nodes, "edges": request.edges},
        "is_public": False,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    MOCK_WORKFLOWS.append(workflow)
    return workflow


@workflows_router.put("/{workflow_id}", response_model=dict)
async def update_workflow(
    workflow_id: str,
    request: UpdateWorkflowRequest,
    authorization: str = Header(None)
):
    """Update workflow"""
    for w in MOCK_WORKFLOWS:
        if w["id"] == workflow_id:
            if request.name is not None:
                w["name"] = request.name
            if request.description is not None:
                w["description"] = request.description
            if request.nodes is not None or request.edges is not None:
                w["graph"]["nodes"] = request.nodes or w["graph"].get("nodes", [])
                w["graph"]["edges"] = request.edges or w["graph"].get("edges", [])
            w["updated_at"] = datetime.utcnow().isoformat() + "Z"
            return w
    raise HTTPException(status_code=404, detail="Workflow not found")


@workflows_router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    authorization: str = Header(None)
):
    """Delete workflow"""
    for i, w in enumerate(MOCK_WORKFLOWS):
        if w["id"] == workflow_id:
            MOCK_WORKFLOWS.pop(i)
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Workflow not found")


@workflows_router.post("/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: str,
    authorization: str = Header(None)
):
    """Publish workflow (make it public)"""
    for w in MOCK_WORKFLOWS:
        if w["id"] == workflow_id:
            w["is_public"] = True
            return {"workflow_id": workflow_id, "is_public": True}
    raise HTTPException(status_code=404, detail="Workflow not found")


@workflows_router.post("/public/{public_id}/fork")
async def fork_workflow(
    public_id: str,
    user_id: str = Query(...),
    authorization: str = Header(None)
):
    """Fork a public workflow"""
    for w in MOCK_WORKFLOWS:
        if w["id"] == public_id:
            forked = {
                **w,
                "id": f"wf-{uuid.uuid4().hex[:8]}",
                "user_id": user_id,
                "name": f"{w['name']} (fork)",
                "is_public": False
            }
            MOCK_WORKFLOWS.append(forked)
            return {"workflow_id": forked["id"], "name": forked["name"]}
    raise HTTPException(status_code=404, detail="Workflow not found")


@workflows_router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: ExecuteWorkflowRequest,
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """Start workflow execution"""
    current_user = verify_token(authorization) or user_id or "anonymous"

    # Verify workflow exists
    workflow = None
    for w in MOCK_WORKFLOWS:
        if w["id"] == workflow_id:
            workflow = w
            break

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    execution_id = f"exec-{uuid.uuid4().hex[:8]}"

    # Create execution
    execution = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "workflow_template_id": workflow_id,
        "file_id": request.file_id,
        "user_id": current_user,
        "workflow_name": workflow["name"],
        "file_name": request.file_path.split("/")[-1],
        "language": request.language,
        "status": "pending",
        "error_message": None,
        "started_at": None,
        "ended_at": None,
        "created_at": datetime.utcnow().isoformat() + "Z"
    }
    MOCK_EXECUTIONS.append(execution)

    # Create nodes for execution
    nodes = []
    for node in workflow["graph"]["nodes"]:
        node_exec = {
            "id": f"en-{uuid.uuid4().hex[:8]}",
            "execution_id": execution_id,
            "node_template_id": None,
            "node_id": node["id"],
            "node_name": node.get("name", node["id"]),
            "status": "pending",
            "progress_percent": 0,
            "progress_message": None,
            "input_data": None,
            "output_data": None,
            "container_id": None,
            "cpu_percent": None,
            "memory_mb": None,
            "execution_time_ms": None,
            "error_message": None,
            "logs_path": None,
            "started_at": None,
            "ended_at": None,
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        nodes.append(node_exec)

    MOCK_EXECUTION_NODES[execution_id] = nodes

    return {"execution_id": execution_id, "status": "pending"}


app.include_router(workflows_router)


# =============================================
# EXECUTION NODES API (detailed)
# =============================================

executions_router = APIRouter(prefix="/api/executions", tags=["executions"])# =============================================
# EXECUTION NODES API (detailed)
# =============================================

executions_router = APIRouter(prefix="/api/executions", tags=["executions"])


@executions_router.get("/{execution_id}/nodes/{node_id}", response_model=dict)
async def get_execution_node(execution_id: str, node_id: str):
    """Get details of specific execution node"""
    nodes = MOCK_EXECUTION_NODES.get(execution_id, [])
    for node in nodes:
        if node["id"] == node_id:
            return node
    raise HTTPException(status_code=404, detail="Node not found")


@executions_router.post("/{execution_id}/nodes/{node_id}/restart", response_model=dict)
async def restart_execution_node(execution_id: str, node_id: str):
    """Restart a failed node with same inputs"""
    nodes = MOCK_EXECUTION_NODES.get(execution_id, [])
    for node in nodes:
        if node["id"] == node_id:
            if node["status"] != "failed":
                raise HTTPException(status_code=400, detail="Can only restart failed nodes")

            # Reset node state
            node["status"] = "pending"
            node["progress_percent"] = 0
            node["progress_message"] = None
            node["error_message"] = None
            node["started_at"] = None
            node["ended_at"] = None

            return node

    raise HTTPException(status_code=404, detail="Node not found")


@executions_router.get("/{execution_id}/nodes/{node_id}/artifacts", response_model=List[dict])
async def get_node_artifacts(execution_id: str, node_id: str):
    """List all artifacts produced by a node"""
    return [a for a in MOCK_ARTIFACTS if a["workflow_id"] == execution_id and a["node_id"] == node_id]


@executions_router.get("/{execution_id}/nodes/{node_id}/artifacts/{artifact_id}/download")
async def download_node_artifact(execution_id: str, node_id: str, artifact_id: str):
    """Download specific artifact (returns mock content)"""
    for a in MOCK_ARTIFACTS:
        if a["id"] == artifact_id:
            # Return mock file content
            content = f"Mock content for {a['name']}\nSize: {a['size_bytes']} bytes"
            return Response(
                content=content,
                media_type=a["mime_type"],
                headers={"Content-Disposition": f"attachment; filename={a['name']}"}
            )
    raise HTTPException(status_code=404, detail="Artifact not found")


@executions_router.get("/{execution_id}/nodes/{node_id}/logs")
async def get_node_logs(execution_id: str, node_id: str):
    """Get execution logs for a node"""
    # Find the execution node by execution_id and find node by node_id prefix
    nodes = MOCK_EXECUTION_NODES.get(execution_id, [])
    for node in nodes:
        if node["id"] == node_id:
            _ = MOCK_NODE_LOGS.get(node_id, "")
            return {"attempt": 1, "url": f"http://localhost:9000/mock-logs/{execution_id}/{node_id}/node.log"}

    raise HTTPException(status_code=404, detail="Node not found")


app.include_router(executions_router)


# =============================================
# NODES API
# =============================================

nodes_router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@nodes_router.get("", response_model=List[dict])
async def list_nodes(user_id: Optional[str] = Query(None)):
    """List all node templates"""
    return MOCK_NODE_TEMPLATES


@nodes_router.get("/plugins")
async def list_plugins():
    """List available plugins"""
    return MOCK_PLUGINS


@nodes_router.get("/plugins/{plugin_id}")
async def get_plugin(plugin_id: str):
    """Get plugin details"""
    for p in MOCK_PLUGINS:
        if p["id"] == plugin_id:
            return p
    raise HTTPException(status_code=404, detail="Plugin not found")


@nodes_router.get("/{node_id}", response_model=dict)
async def get_node(node_id: str):
    """Get node template by ID"""
    for n in MOCK_NODE_TEMPLATES:
        if n["id"] == node_id:
            return n
    raise HTTPException(status_code=404, detail="Node not found")


@nodes_router.post("", response_model=dict)
async def create_node(
    request: CreateNodeRequest,
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """Create a new node template"""
    node = {
        "id": f"node-{uuid.uuid4().hex[:8]}",
        "user_id": verify_token(authorization) or user_id,
        "plugin_id": request.plugin_id,
        "name": request.name,
        "description": request.description,
        "parameters": request.parameters,
        "input_mapping": request.input_mapping or [],
        "prompt_id": request.prompt_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    MOCK_NODE_TEMPLATES.append(node)
    return node


@nodes_router.put("/{node_id}", response_model=dict)
async def update_node(
    node_id: str,
    request: UpdateNodeRequest,
    authorization: str = Header(None)
):
    """Update node template"""
    for n in MOCK_NODE_TEMPLATES:
        if n["id"] == node_id:
            if request.name is not None:
                n["name"] = request.name
            if request.description is not None:
                n["description"] = request.description
            if request.parameters is not None:
                n["parameters"] = request.parameters
            if request.input_mapping is not None:
                n["input_mapping"] = request.input_mapping
            if request.prompt_id is not None:
                n["prompt_id"] = request.prompt_id
            n["updated_at"] = datetime.utcnow().isoformat() + "Z"
            return n
    raise HTTPException(status_code=404, detail="Node not found")


@nodes_router.delete("/{node_id}")
async def delete_node(
    node_id: str,
    authorization: str = Header(None)
):
    """Delete node template"""
    for i, n in enumerate(MOCK_NODE_TEMPLATES):
        if n["id"] == node_id:
            MOCK_NODE_TEMPLATES.pop(i)
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Node not found")


app.include_router(nodes_router)


# =============================================
# PROMPTS API
# =============================================

prompts_router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@prompts_router.get("", response_model=List[dict])
async def list_prompts(
    user_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """List prompts with optional search"""
    current_user = verify_token(authorization)

    prompts = MOCK_PROMPTS

    # Filter by user if specified
    if user_id or current_user:
        prompts = [p for p in prompts if p.get("user_id") in [user_id, current_user, None]]
    else:
        prompts = [p for p in prompts if p.get("user_id") is None]

    # Filter by search term
    if search:
        search_lower = search.lower()
        prompts = [p for p in prompts if search_lower in p["name"].lower()]

    return prompts


@prompts_router.get("/{prompt_id}", response_model=dict)
async def get_prompt(prompt_id: str):
    """Get prompt by ID"""
    for p in MOCK_PROMPTS:
        if p["id"] == prompt_id:
            return p
    raise HTTPException(status_code=404, detail="Prompt not found")


@prompts_router.post("", response_model=dict)
async def create_prompt(
    request: CreatePromptRequest,
    user_id: Optional[str] = Query(None),
    authorization: str = Header(None)
):
    """Create a new prompt"""
    current_user = verify_token(authorization) or user_id

    # Auto-detect variables from template
    variables = request.variables or []
    if not variables and request.user_prompt_template:
        import re
        variables = list(set(re.findall(r'\{\{(\w+)\}\}', request.user_prompt_template)))

    prompt = {
        "id": f"prompt-{uuid.uuid4().hex[:8]}",
        "user_id": current_user,
        "name": request.name,
        "system_prompt": request.system_prompt,
        "user_prompt_template": request.user_prompt_template,
        "variables": variables,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    MOCK_PROMPTS.append(prompt)
    return prompt


@prompts_router.put("/{prompt_id}", response_model=dict)
async def update_prompt(
    prompt_id: str,
    request: UpdatePromptRequest,
    authorization: str = Header(None)
):
    """Update prompt"""
    for p in MOCK_PROMPTS:
        if p["id"] == prompt_id:
            if request.name is not None:
                p["name"] = request.name
            if request.system_prompt is not None:
                p["system_prompt"] = request.system_prompt
            if request.user_prompt_template is not None:
                p["user_prompt_template"] = request.user_prompt_template
            if request.variables is not None:
                p["variables"] = request.variables
            p["updated_at"] = datetime.utcnow().isoformat() + "Z"
            return p
    raise HTTPException(status_code=404, detail="Prompt not found")


@prompts_router.delete("/{prompt_id}")
async def delete_prompt(
    prompt_id: str,
    authorization: str = Header(None)
):
    """Delete prompt"""
    for i, p in enumerate(MOCK_PROMPTS):
        if p["id"] == prompt_id:
            MOCK_PROMPTS.pop(i)
            return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Prompt not found")


@prompts_router.get("/{prompt_id}/render")
async def render_prompt(
    prompt_id: str,
    name: Optional[str] = Query(None),
    value: Optional[str] = Query(None)
):
    """Render prompt with variables substituted"""
    for p in MOCK_PROMPTS:
        if p["id"] == prompt_id:
            system = p.get("system_prompt", "") or ""
            user_template = p.get("user_prompt_template", "") or ""
            if name and value:
                system = system.replace(f"{{{{{name}}}}}", value)
                user_template = user_template.replace(f"{{{{{name}}}}}", value)
            return {"system_prompt": system, "user_prompt": user_template}
    raise HTTPException(status_code=404, detail="Prompt not found")


app.include_router(prompts_router)


# =============================================
# LEGACY API ROUTES
# =============================================

legacy_router = APIRouter()


@legacy_router.get("/api/files")
async def get_files():
    """List all files"""
    return MOCK_FILES


@legacy_router.get("/api/files/{file_id}")
async def get_file_details(file_id: str):
    """Get file details"""
    for f in MOCK_FILES:
        if f["id"] == file_id:
            return f
    raise HTTPException(status_code=404, detail="File not found")


@legacy_router.get("/api/workflows/history")
async def get_workflows_history():
    """Legacy: get workflow history (executions)"""
    return MOCK_EXECUTIONS


@legacy_router.get("/api/workflows/history/{workflow_id}")
async def get_workflow_details(workflow_id: str):
    """Legacy: get execution details"""
    for e in MOCK_EXECUTIONS:
        if e["id"] == workflow_id:
            return e
    raise HTTPException(status_code=404, detail="Execution not found")


@legacy_router.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Get artifact by ID"""
    for a in MOCK_ARTIFACTS:
        if a["id"] == artifact_id:
            return a
    raise HTTPException(status_code=404, detail="Artifact not found")


@legacy_router.get("/api/queue/status")
async def get_queue_status():
    """Get queue status"""
    return MOCK_QUEUE_STATUS


@legacy_router.post("/api/alerts/webhook")
async def receive_alert(alert_data: dict):
    """Receive alerts (mock)"""
    return {"status": "ok", "received": len(alert_data.get("alerts", []))}


app.include_router(legacy_router)


# =============================================
# METRICS (mock)
# =============================================

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return """
# HELP lectify_workflows_total Total number of workflows
# TYPE lectify_workflows_total gauge
lectify_workflows_total 3

# HELP lectify_executions_total Total number of executions
# TYPE lectify_executions_total counter
lectify_executions_total 6

# HELP lectify_active_workflows Current active workflows
# TYPE lectify_active_workflows gauge
lectify_active_workflows 1
""".strip()


# =============================================
# RUN
# =============================================

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("MOCK BACKEND FOR FRONTEND DEVELOPMENT")
    print("=" * 60)
    print("URL: http://localhost:5002")
    print()
    print("Test credentials:")
    print("  Username: demo")
    print("  Password: password123")
    print()
    print("Routes:")
    print("  /login              - Login page")
    print("  /forgot-password    - Forgot password page")
    print("  /reset-password     - Reset password page")
    print("  /profile            - Profile page")
    print("  /executions         - Executions list")
    print("  /executions/{id}    - Execution detail")
    print("  /prompts            - Prompts library")
    print()
    print("API Endpoints:")
    print("  POST /api/auth/login")
    print("  POST /api/auth/logout")
    print("  POST /api/auth/forgot-password")
    print("  POST /api/auth/reset-password")
    print("  GET  /api/profile")
    print("  PUT  /api/profile")
    print("  PUT  /api/profile/password")
    print("  GET  /api/workflows")
    print("  GET  /api/workflows/executions")
    print("  GET  /api/executions/{id}/nodes/{node_id}")
    print("  POST /api/executions/{id}/nodes/{node_id}/restart")
    print("  GET  /api/executions/{id}/nodes/{node_id}/artifacts")
    print("  GET  /api/executions/{id}/nodes/{node_id}/logs")
    print("  GET  /api/prompts?search=xxx")
    print("  ...")
    print("=" * 60)
    uvicorn.run("mock.main_mock:app", host="0.0.0.0", port=5002, reload=True)
