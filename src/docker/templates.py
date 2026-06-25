"""
Dockerfile templates for plugins
"""

DOCKERFILE_TEMPLATE = """FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    ffmpeg \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY {plugin_path}/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy plugin code
COPY . /app/

# Create directories for input/output
RUN mkdir -p /input /output

# Environment
ENV PYTHONUNBUFFERED=1
ENV PLUGIN_INPUT=/input/input.json
ENV PLUGIN_OUTPUT=/output/output.json

CMD ["python", "-m", "src.plugins.runner"]
"""

BASE_DOCKERFILE = """FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \\
    ffmpeg \\
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

CMD ["python", "-m", "src.plugins.runner"]
"""

REQUIREMENTS_TEMPLATE = """
pydantic>=2.0.0
pydub>=0.25.0
"""


def get_dockerfile_for_plugin(plugin_id: str, plugin_path: str = None) -> str:
    """Get Dockerfile content for a specific plugin"""
    if plugin_path:
        return DOCKERFILE_TEMPLATE.format(plugin_path=plugin_path)
    return BASE_DOCKERFILE


def get_requirements_for_plugin(plugin_id: str) -> str:
    """Get requirements.txt content for a specific plugin"""

    base_reqs = [
        "pydantic>=2.0.0",
        "httpx>=0.25.0",
    ]

    # Plugin-specific requirements
    if plugin_id == "media_converter":
        base_reqs.append("pydub>=0.25.0")
    elif plugin_id == "speech_to_text":
        base_reqs.append("openai>=1.0.0")
        base_reqs.append("pydub>=0.25.0")
    elif plugin_id == "text_to_md":
        base_reqs.append("openai>=1.0.0")
    elif plugin_id == "text_to_latex":
        base_reqs.append("openai>=1.0.0")
    elif plugin_id == "latex_to_pdf":
        base_reqs.append("openai>=1.0.0")
    elif plugin_id == "llm_request":
        base_reqs.append("openai>=1.0.0")

    return "\n".join(base_reqs) + "\n"
