FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCHEMA_AUTO_CREATE=false \
    REQUIRE_TESSERACT=true \
    APP_ENV=production

RUN apt-get update \
    && apt-get install --no-install-recommends -y tesseract-ocr fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system taasheera \
    && useradd --system --gid taasheera --home-dir /app taasheera

WORKDIR /app
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock

COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini migrate.py render_start.py ./
RUN mkdir -p /app/storage \
    && chown -R taasheera:taasheera /app/storage

USER taasheera
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
