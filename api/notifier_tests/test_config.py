from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from brerc_notifier.config import SmtpDestination, WebhookDestination, load_config
from brerc_notifier.errors import NotifierConfigurationError


def _write(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _environment(tmp_path: Path) -> dict[str, str]:
    files = {
        "PGSERVICEFILE": _write(
            tmp_path / "pg_service.conf",
            "[notify]\n"
            "host=db.example\n"
            "port=5432\n"
            "dbname=brerc_publication\n"
            "user=brerc_notifier_service\n"
            "sslmode=verify-full\n",
        ),
        "BRERC_NOTIFIER_PGPASSFILE": _write(
            tmp_path / "pgpass",
            "db.example:5432:brerc_publication:brerc_notifier_service:private-db-password",
        ),
        "BRERC_NOTIFIER_SSLROOTCERT": _write(tmp_path / "ca.pem", "private-ca"),
        "BRERC_NOTIFIER_SMTP_USERNAME_FILE": _write(tmp_path / "smtp-user", "private-user"),
        "BRERC_NOTIFIER_SMTP_PASSWORD_FILE": _write(
            tmp_path / "smtp-password", "private-password"
        ),
        "BRERC_NOTIFIER_WEBHOOK_SECRET_FILE": _write(
            tmp_path / "webhook-secret", "x" * 32
        ),
    }
    return {
        "BRERC_NOTIFIER_PGSERVICE": "notify",
        **{name: str(path) for name, path in files.items()},
    }


def _yaml(provider: str = "smtp") -> str:
    destination = (
        """
    provider: smtp
    host: smtp.example.org
    port: 465
    from_address: dashboard@example.org
    to_addresses:
      - operator@example.org
    username_file_env: BRERC_NOTIFIER_SMTP_USERNAME_FILE
    password_file_env: BRERC_NOTIFIER_SMTP_PASSWORD_FILE
"""
        if provider == "smtp"
        else """
    provider: webhook
    url: https://alerts.example.org/brerc
    secret_file_env: BRERC_NOTIFIER_WEBHOOK_SECRET_FILE
"""
    )
    return f"""config_version: brerc-notifier-v1
database:
  expected_database: brerc_publication
  expected_login: brerc_notifier_service
  expected_role: brerc_notifier
  expected_migration_version: 2
  connect_timeout_seconds: 10
  statement_timeout_ms: 5000
  service_env: BRERC_NOTIFIER_PGSERVICE
  service_file_env: PGSERVICEFILE
  passfile_env: BRERC_NOTIFIER_PGPASSFILE
  sslrootcert_env: BRERC_NOTIFIER_SSLROOTCERT
  sslmode: verify-full
runtime:
  batch_size: 1
  lease_seconds: 120
  poll_interval_seconds: 10
  delivery_timeout_seconds: 15
  provider_probe_interval_seconds: 300
  readiness_stale_seconds: 60
  health_host: 0.0.0.0
  health_port: 9108
destinations:
  etl-operations:
{destination}"""


def test_loads_smtp_configuration_and_redacts_every_private_value(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml())
    environ = _environment(tmp_path)

    config = load_config(config_path, environ=environ)

    destination = config.destinations["etl-operations"]
    assert isinstance(destination, SmtpDestination)
    assert config.database.parameters()["sslmode"] == "verify-full"
    rendered = f"{config!r} {config.database!r} {destination!r}"
    for private in (
        "private-user",
        "private-password",
        "operator@example.org",
        "smtp.example.org",
        "brerc_publication",
        "brerc_notifier_service",
    ):
        assert private not in rendered


def test_loads_https_webhook_with_secret_file(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml("webhook"))
    config = load_config(config_path, environ=_environment(tmp_path))

    destination = config.destinations["etl-operations"]
    assert isinstance(destination, WebhookDestination)
    assert destination.secret == b"x" * 32
    assert "alerts.example.org" not in repr(destination)
    assert "x" * 32 not in repr(config)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda text: text.replace("sslmode: verify-full", "sslmode: require"),
        lambda text: text.replace("url: https://", "url: http://"),
        lambda text: text.replace("expected_role: brerc_notifier", "expected_role: postgres"),
        lambda text: text.replace(
            "  delivery_timeout_seconds: 15", "  delivery_timeout_seconds: 30"
        ),
        lambda text: text.replace(
            "  connect_timeout_seconds: 10", "  connect_timeout_seconds: 30"
        ),
        lambda text: text.replace(
            "  provider_probe_interval_seconds: 300",
            "  provider_probe_interval_seconds: 5",
        ),
        lambda text: text.replace("  batch_size: 1", "  batch_size: 1\n  unknown: 1"),
        lambda text: text.replace(
            "config_version: brerc-notifier-v1",
            "config_version: brerc-notifier-v1\nconfig_version: duplicate",
        ),
        lambda text: text
        + "\n  unexpected:\n"
        + "    provider: webhook\n"
        + "    url: https://unexpected.example.org/notify\n"
        + "    secret_file_env: BRERC_NOTIFIER_WEBHOOK_SECRET_FILE\n",
    ),
)
def test_rejects_weakened_unknown_or_ambiguous_configuration(
    tmp_path: Path, mutation: object
) -> None:
    config_path = _write(tmp_path / "notifier.yaml", mutation(_yaml("webhook")))  # type: ignore[operator]
    with pytest.raises(NotifierConfigurationError) as rejected:
        load_config(config_path, environ=_environment(tmp_path))
    assert str(rejected.value) == "NOTIFIER_CONFIGURATION_INVALID"


def test_rejects_ambient_password_and_relative_config_path(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml())
    environ = {**_environment(tmp_path), "PGPASSWORD": "must-not-be-used"}
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)
    with pytest.raises(NotifierConfigurationError):
        load_config(Path("notifier.yaml"), environ=_environment(tmp_path))


def test_rejects_missing_or_reused_protected_files(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml())
    environ = _environment(tmp_path)
    environ["BRERC_NOTIFIER_SMTP_PASSWORD_FILE"] = environ[
        "BRERC_NOTIFIER_SMTP_USERNAME_FILE"
    ]
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)

    environ = _environment(tmp_path)
    Path(environ["BRERC_NOTIFIER_SMTP_PASSWORD_FILE"]).chmod(0o644)
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)

    environ = _environment(tmp_path)
    environ["BRERC_NOTIFIER_SSLROOTCERT"] = str(tmp_path / "absent.pem")
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)


def test_rejects_permissive_config_or_ambiguous_service_file(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml())
    environ = _environment(tmp_path)

    config_path.chmod(0o644)
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)

    config_path.chmod(0o600)
    service_file = Path(environ["PGSERVICEFILE"])
    _write(
        service_file,
        service_file.read_text(encoding="utf-8") + "password=must-not-be-here\n",
    )
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)

    _write(
        service_file,
        "[notify]\n"
        "host=db.example\n"
        "port=5432\n"
        "dbname=brerc_publication\n"
        "user=brerc_notifier_service\n"
        "sslmode=verify-full\n"
        "[second-service]\n"
        "host=other.example\n",
    )
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)


def test_rejects_ambiguous_passfile_or_cross_secret_reuse(tmp_path: Path) -> None:
    config_path = _write(tmp_path / "notifier.yaml", _yaml())
    environ = _environment(tmp_path)
    passfile = Path(environ["BRERC_NOTIFIER_PGPASSFILE"])

    _write(
        passfile,
        "db.example:5432:brerc_publication:brerc_notifier_service:private-db-password\n"
        "db.example:5432:brerc_publication:admin:admin-password\n",
    )
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)

    environ = _environment(tmp_path)
    environ["BRERC_NOTIFIER_SMTP_USERNAME_FILE"] = environ[
        "BRERC_NOTIFIER_PGPASSFILE"
    ]
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=environ)


def test_rejects_multiple_direct_email_recipients(tmp_path: Path) -> None:
    config_path = _write(
        tmp_path / "notifier.yaml",
        _yaml().replace(
            "      - operator@example.org",
            "      - operator@example.org\n      - second@example.org",
        ),
    )
    with pytest.raises(NotifierConfigurationError):
        load_config(config_path, environ=_environment(tmp_path))


def test_notifier_container_and_compose_overlay_keep_the_private_security_boundary() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "api" / "Dockerfile.notifier").read_text(encoding="utf-8")
    overlay = yaml.safe_load(
        (root / "deploy" / "notifier.compose.yaml").read_text(encoding="utf-8")
    )
    service = overlay["services"]["notifier"]

    assert "USER 65532:65532" in dockerfile
    assert "python:3.12.14-slim@sha256:" in dockerfile
    assert "build" not in service
    assert "@${BRERC_NOTIFIER_IMAGE_DIGEST" in service["image"]
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in service
    assert service["expose"] == ["9108"]
    assert service["networks"] == ["notifier_database", "notifier_control"]
    assert "/ready" in service["healthcheck"]["test"][-1]
    mounted = {item["source"] for item in service["secrets"]}
    assert mounted == {
        "notifier_config",
        "notifier_pg_service",
        "notifier_pg_passfile",
        "notifier_pg_ca",
        "notifier_smtp_username",
        "notifier_smtp_password",
    }
    assert all(item["mode"] == 0o400 for item in service["secrets"])
    dockerignore = (root / "api" / ".dockerignore").read_text(encoding="utf-8")
    for secret_pattern in ("*pgpass*", "*.pem", "*.key", "*password*", "*secret*"):
        assert secret_pattern in dockerignore
