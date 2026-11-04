FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/kora ./kora
RUN pip install .

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

RUN useradd --create-home --uid 10001 kora \
    && mkdir -p /data/cache \
    && chown -R kora:kora /data
USER kora

EXPOSE 8000

CMD ["uvicorn", "kora.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
