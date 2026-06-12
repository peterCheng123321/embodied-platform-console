FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/pyproject.toml backend/pyproject.toml
RUN pip install --no-cache-dir -e backend 2>/dev/null || true
COPY backend backend
COPY apps apps
COPY scripts scripts
RUN pip install --no-cache-dir -e backend
ENV XINGJU_EMBODIED_PLATFORM_DATA_ROOT=/srv/backend/data/embodied_platform \
    XINGJU_EMBODIED_DATA_ROOT=/srv/backend/data/embodied \
    XINGJU_EMBODIED_CACHE_ROOT=/srv/backend/data/embodied_cache
EXPOSE 8099
HEALTHCHECK --interval=30s --timeout=3s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8099/healthz')"
CMD ["bash", "scripts/run.sh"]
