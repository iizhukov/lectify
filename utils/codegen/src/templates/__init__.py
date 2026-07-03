import jinja2

from pathlib import Path


TEMPLATES_DIR = Path(__file__).parent

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
