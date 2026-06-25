# routers/web_router.py

import pathlib

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, RedirectResponse


web_router = APIRouter()

HTML_PATH = pathlib.Path(__file__).parent.parent.parent / "resources" / "templates"


def read_html(filename: str):
    path = HTML_PATH / filename
    if not path.exists():
        return HTMLResponse(f"<h3>Error: {filename} not found!</h3>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@web_router.get("/")
async def index():
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
