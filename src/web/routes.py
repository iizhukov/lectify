# routers/web_router.py

import pathlib

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


web_router = APIRouter()

HTML_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "resources"
    / "templates"
)


def read_html(filename: str):
    path = HTML_PATH / filename

    if not path.exists():
        return HTMLResponse(
            f"<h3>Ошибка: {filename} не найден!</h3>",
            status_code=404
        )

    return HTMLResponse(
        path.read_text(encoding="utf-8")
    )


@web_router.get("/", response_class=HTMLResponse)
async def index():
    return read_html("index.html")


@web_router.get("/files/{file_id}", response_class=HTMLResponse)
async def file_details(file_id: str):
    return read_html("file_details.html")
