FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /uvx /bin/
WORKDIR /app
ARG UV_INDEX_URL
ENV UV_HTTP_TIMEOUT=900 UV_CONCURRENT_DOWNLOADS=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY --from=build /app/app ./app
COPY --from=build /app/migrations ./migrations
COPY --from=build /app/alembic.ini ./alembic.ini
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
