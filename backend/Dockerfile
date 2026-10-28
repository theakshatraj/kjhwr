# Wind Forecast Decision Portal - backend image.
#
# Python 3.12 matches the runtime verified on Vercel in the Phase 2 PoC, so the
# container and the deployment run the same interpreter as production.
#
# Build from the backend directory (the context is `backend/`):
#   docker build -t wind-portal-api backend
# Run:
#   docker run --rm -p 8000:8000 wind-portal-api
# Docs:
#   http://localhost:8000/api/docs

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY app ./app
# The processed snapshot is baked in: the API serves a fixed historical analysis.
COPY data/processed ./data/processed
COPY data/provenance.json ./data/provenance.json

# Non-root runtime.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
