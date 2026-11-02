FROM python:3.12-slim
ARG PLUGIN_SYSTEM_PACKAGES=""
RUN apt-get update && apt-get install -y --no-install-recommends docker-cli ca-certificates ffmpeg ${PLUGIN_SYSTEM_PACKAGES} && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY project /app
ENV PYTHONUNBUFFERED=1 CODEGEN_ROOT=/app LECTIFY_ROOT=/app
ENTRYPOINT ["python", "/app/infra/local/entrypoint.py"]
