# Read-only public API.
#
# Installs the package with its pinned adapter extra rather than a loose
# requirements file, so the image gets exactly the psycopg/PyYAML/FastAPI
# versions the test suite ran against.
FROM python:3.13-slim

WORKDIR /app

# Dependency metadata first, so the install layer is cached until pins change.
COPY pyproject.toml README.md LICENSE ./
COPY etl ./etl
COPY brerc_source ./brerc_source
COPY brerc_loader ./brerc_loader
COPY app ./app

RUN pip install --no-cache-dir ".[connector-binary,api]"

# Runs unprivileged: the API only ever reads, and nothing in the image needs
# to be writable at runtime.
RUN useradd --system --uid 10001 brerc && chown -R brerc /app
USER brerc

EXPOSE 8000

# No --reload, no --workers guesswork: one worker per container, scaled by the
# orchestrator if it ever needs to be.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
