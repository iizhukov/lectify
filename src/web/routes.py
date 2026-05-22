import pathlib

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


web_router = APIRouter()

HTML_PATH = pathlib.Path(__file__).parent.parent.parent / "resources" / "templates"


@web_router.get("/", response_class=HTMLResponse)
async def index():
    index_html = HTML_PATH / "index.html"
    if not index_html.exists():
        return "<h3>Ошибка: index.html не найден в папке resources/templates!</h3>"
    
    return index_html.read_text(encoding="utf-8")
