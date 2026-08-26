# Read-only public API. The image deliberately does not contain the ETL,
# connector, loader, migrations, tests, client data or write-capable commands.
FROM python:3.13-slim

ENV APP_ENV=prod \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/brerc-api

# Resolve the API's pinned direct dependencies from the single project source
# of truth without installing the combined repository wheel (which also
# defines loader/source commands). Python 3.13 supplies tomllib in the stdlib.
COPY pyproject.toml ./
RUN python -c "import pathlib,tomllib; d=tomllib.loads(pathlib.Path('pyproject.toml').read_text()); pathlib.Path('/tmp/api-requirements.txt').write_text('\\n'.join(d['project']['optional-dependencies']['api'])+'\\n')" \
    && python -m pip install --no-cache-dir --no-compile -r /tmp/api-requirements.txt \
    && rm /tmp/api-requirements.txt

# This is the only repository source tree copied into the public image.
COPY app ./app

# Refuse the build if the app is incomplete or a write-capable repository
# package somehow crossed the Docker context boundary.
RUN python -c "import importlib.util; import app.main; assert importlib.util.find_spec('brerc_loader') is None; assert importlib.util.find_spec('brerc_source') is None; assert importlib.util.find_spec('etl') is None"

# Files remain root-owned and non-writable by the serving process.
RUN groupadd --gid 10001 brerc \
    && useradd --uid 10001 --gid 10001 --no-create-home \
        --home-dir /nonexistent --shell /usr/sbin/nologin brerc
USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
