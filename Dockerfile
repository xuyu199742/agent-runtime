FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.29 /uv /uvx /bin/
WORKDIR /app
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
