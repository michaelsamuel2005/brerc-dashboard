# Read-only FastAPI service for the BRERC public dashboard.
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Install dependencies first (better layer caching), then the app.
COPY pyproject.toml ./
COPY app ./app
RUN pip install .

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# API_ROOT_PATH=/api is set by compose so the OpenAPI docs work behind the proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
