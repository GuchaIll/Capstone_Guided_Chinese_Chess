# ============================================================
# Server Dockerfile - Python Coaching Server
# ============================================================
# FastAPI + agent orchestration system
# Exposes HTTP/WS on port 5000
# ============================================================

FROM python:3.12-slim

WORKDIR /app

# Install dependencies (torch CPU-only to minimize image size)
# BuildKit cache mount keeps the pip download cache between builds — avoids
# re-downloading the ~700 MB torch wheel on every `docker compose up --build`.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r requirements.txt

# Pre-download the embedding model so startup doesn't depend on network speed.
# Placed BEFORE `COPY . .` so code changes don't invalidate this ~820s layer.
ARG EMBEDDING_MODEL=BAAI/bge-m3
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p logs agent_orchestration/.agent/profiles chroma_db

EXPOSE 5000

# Use uvicorn directly for production
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000", "--log-level", "info"]
