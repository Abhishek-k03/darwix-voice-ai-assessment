# Build context: repository root (needs data/ for the KB sources).
FROM python:3.13-slim

ENV UV_LINK_MODE=copy PYTHONUNBUFFERED=1 HF_HUB_DISABLE_SYMLINKS_WARNING=1
RUN pip install --no-cache-dir uv

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY data/sources /app/data/sources
COPY data/kb /app/data/kb
ENV PATH="/app/backend/.venv/bin:$PATH"

EXPOSE 8000
CMD ["sh", "-c", "python -m kb.build --if-missing && python main.py"]
