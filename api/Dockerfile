# Container image for the read-only FastAPI service (B9).
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when requirements change).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code (see .dockerignore for what is left out — .env, tests).
COPY app ./app

# The API listens on 8000 inside the container.
EXPOSE 8000

# No --reload in a container image; this is the production run command.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
