"""Static regressions for the inert production-serving examples.

These tests intentionally do not claim target-host acceptance. They prevent the
reviewed topology and least-privilege boundaries from silently drifting before
BRERC renders the examples and validates them on its actual Linux host.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
PRODUCTION = REPOSITORY / "deploy" / "production"
README = PRODUCTION / "README.md"
API_UNIT = PRODUCTION / "brerc-public-api.service.example"
MONITOR_UNIT = PRODUCTION / "brerc-run-dashboard.service.example"
API_ENV = PRODUCTION / "public-api.env.example"
MONITOR_ENV = PRODUCTION / "run-dashboard.env.example"
PUBLIC_NGINX = PRODUCTION / "nginx-public.conf.example"
INTERNAL_NGINX = PRODUCTION / "nginx-internal.conf.example"
ROOT_COMPOSE = REPOSITORY / "docker-compose.yml"
ROOT_CADDY = REPOSITORY / "Caddyfile"
LINUX_ACCEPTANCE = REPOSITORY / "deploy" / "validation" / "LINUX_ACCEPTANCE.md"
ACCEPTANCE_RECORD = (
    REPOSITORY / "deploy" / "validation" / "TARGET_LINUX_ACCEPTANCE_RECORD.md.example"
)
RUNTIME_LOGIN_AUDIT = REPOSITORY / "deploy" / "validation" / "audit_runtime_logins.sql"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _directives(text: str, name: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"{name}=")]


def test_only_inert_examples_are_tracked() -> None:
    expected = {
        "README.md",
        "api-pg-service.conf.example",
        "brerc-public-api.service.example",
        "brerc-run-dashboard.service.example",
        "monitor-pg-service.conf.example",
        "nginx-internal.conf.example",
        "nginx-public.conf.example",
        "public-api.env.example",
        "run-dashboard.env.example",
    }
    assert {path.name for path in PRODUCTION.iterdir()} == expected
    assert not tuple(PRODUCTION.glob("*.service"))
    assert not tuple(PRODUCTION.glob("*.conf"))
    for unit in (API_UNIT, MONITOR_UNIT):
        text = _text(unit)
        assert "EXAMPLE ONLY" in text
        assert "[Install]" in text
        assert "WantedBy=multi-user.target" in text


def test_units_are_pinned_to_immutable_separate_runtimes_and_loopback() -> None:
    api = _text(API_UNIT)
    monitor = _text(MONITOR_UNIT)
    placeholder = "REPLACE_WITH_APPROVED_ARTIFACT_ID"

    assert placeholder in api and placeholder in monitor
    assert "/opt/brerc-dashboard/current" not in api + monitor
    assert "/api-runtime/venv/bin/uvicorn app.main:app" in api
    assert "--host 127.0.0.1 --port 8000" in api
    assert "/run-dashboard-runtime/venv/bin/uvicorn app:app" in monitor
    assert "--host 127.0.0.1 --port 8100" in monitor
    assert "--host 0.0.0.0" not in api + monitor
    assert "brerc-load" not in api + monitor
    assert "nightly_job" not in api + monitor
    assert "User=brerc-api" in api
    assert "User=brerc-monitor-ui" in monitor
    assert "User=brerc-loader" not in api + monitor
    assert "run-dashboard-runtime" not in api
    assert "api-runtime" not in monitor


def test_units_keep_secrets_external_and_apply_hardening() -> None:
    api = _text(API_UNIT)
    monitor = _text(MONITOR_UNIT)
    assert "public-api.secrets.env" not in api
    assert "AssertFileNotEmpty=/etc/brerc/production/api/pg_service.conf" in api
    assert "AssertFileNotEmpty=/etc/brerc/production/api/api.pgpass" in api
    assert "UnsetEnvironment=PGPASSWORD DATABASE_URL" in api
    assert "EnvironmentFile=/etc/brerc/production/monitor/run-dashboard.secrets.env" in monitor
    for unit in (api, monitor):
        assert "UnsetEnvironment=PGPASSWORD" in unit
        assert _directives(unit, "NoNewPrivileges") == ["NoNewPrivileges=true"]
        assert _directives(unit, "PrivateTmp") == ["PrivateTmp=true"]
        assert _directives(unit, "PrivateDevices") == ["PrivateDevices=true"]
        assert _directives(unit, "ProtectSystem") == ["ProtectSystem=strict"]
        assert _directives(unit, "ProtectHome") == ["ProtectHome=true"]
        assert _directives(unit, "CapabilityBoundingSet") == ["CapabilityBoundingSet="]
        assert _directives(unit, "AmbientCapabilities") == ["AmbientCapabilities="]
        assert _directives(unit, "RestrictAddressFamilies") == [
            "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6"
        ]
        assert not _directives(unit, "ReadWritePaths")


def test_public_vhost_serves_react_and_same_origin_api_only() -> None:
    public = _text(PUBLIC_NGINX)
    assert (
        "root /opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/web/dist;"
    ) in public
    assert "location ^~ /api/" in public
    assert "proxy_pass http://127.0.0.1:8000;" in public
    assert "try_files $uri $uri/ /index.html;" in public
    assert "max-age=31536000, immutable" in public
    assert "https://$host" not in public
    assert "https://REPLACE_WITH_PUBLIC_DASHBOARD_HOSTNAME$request_uri" in public
    assert public.count('Cache-Control "no-store, max-age=0"') == 2
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains"' in public
    assert "proxy_set_header Host $host" not in public
    assert "location = /tiles { return 404; }" in public
    assert "location ^~ /tiles/ { return 404; }" in public
    assert "location = /run-dashboard { return 404; }" in public
    assert "location ^~ /run-dashboard/ { return 404; }" in public
    worker_location = re.search(
        r"location = /maplibre-gl-worker\.cjs \{(?P<body>.*?)\n    \}",
        public,
        flags=re.DOTALL,
    )
    assert worker_location is not None
    worker_body = worker_location.group("body")
    assert "try_files $uri =404;" in worker_body
    assert "default_type application/javascript;" in worker_body
    assert 'Cache-Control "no-cache, no-store, must-revalidate" always;' in worker_body
    assert 'X-Content-Type-Options "nosniff" always;' in worker_body
    assert "127.0.0.1:8100" not in public
    assert "martin" not in public.lower()
    csp_lines = [
        line.strip()
        for line in public.splitlines()
        if line.strip().startswith("add_header Content-Security-Policy ")
    ]
    # nginx stops inheriting all parent add_header values as soon as a location
    # declares one, so the server and all five header-setting locations require
    # the complete CSP explicitly.
    assert len(csp_lines) == 6
    for line in csp_lines:
        assert "default-src 'self'" in line
        assert "object-src 'none'" in line
        assert "script-src 'self'" in line
        assert "worker-src 'self' blob:" in line
        assert line.count("REPLACE_WITH_APPROVED_BASEMAP_ORIGIN") == 2
        for directive in line.split(";"):
            if "REPLACE_WITH_APPROVED_BASEMAP_ORIGIN" in directive:
                assert directive.strip().startswith(("img-src ", "connect-src "))


def test_internal_vhost_is_separate_private_and_authenticates_in_the_app() -> None:
    public = _text(PUBLIC_NGINX)
    internal = _text(INTERNAL_NGINX)
    assert "REPLACE_WITH_APPROVED_PRIVATE_IP:443" in internal
    assert "REPLACE_WITH_PRIVATE_RUN_DASHBOARD_HOSTNAME" in internal
    assert "allow REPLACE_WITH_APPROVED_OPERATOR_CIDR;" in internal
    assert "deny all;" in internal
    assert "proxy_pass http://127.0.0.1:8100;" in internal
    assert 'Cache-Control "no-store, max-age=0"' in internal
    assert "127.0.0.1:8000" not in internal
    assert "/web/dist" not in internal
    assert "REPLACE_WITH_PRIVATE_RUN_DASHBOARD_HOSTNAME" not in public
    assert "proxy_set_header Host $host" not in internal


def test_tracked_production_examples_contain_no_credentials_or_dsns() -> None:
    combined = "\n".join(_text(path) for path in sorted(PRODUCTION.iterdir()))
    assert "postgresql://" not in combined.lower()
    assert "postgres://" not in combined.lower()
    assert not re.search(r"(?m)^(?:DATABASE_URL|PGPASSWORD)=\S+", combined)
    assert not re.search(r"(?m)^DASHBOARD_PASSWORD=\S+", combined)
    assert not re.search(r"(?m)^DASHBOARD_SECRET_KEY=\S+", combined)
    assert "CHANGE_ME" not in combined


def test_environment_examples_are_nonsecret_and_fail_closed() -> None:
    api = _text(API_ENV)
    monitor = _text(MONITOR_ENV)
    assert "APP_ENV=prod" not in api
    assert "Environment=APP_ENV=prod" in _text(API_UNIT)
    assert "SPECIES_INFO_ENABLED=false" in api
    assert "DATABASE_URL=" not in api
    assert "BRERC_API_DB_MODE=service" in api
    assert "BRERC_API_DB_SERVICE=REPLACE_WITH_" in api
    assert "PGSERVICEFILE=/etc/brerc/production/api/pg_service.conf" in api
    assert "BRERC_API_DB_PASSFILE=/etc/brerc/production/api/api.pgpass" in api
    assert "BRERC_API_DB_SSLROOTCERT=/etc/brerc/production/api/postgres-ca.pem" in api
    assert "BRERC_API_EXPECTED_DATABASE=REPLACE_WITH_" in api
    assert "BRERC_API_EXPECTED_ROLE=REPLACE_WITH_" in api
    assert "DASHBOARD_ENV=prod" not in monitor
    assert "Environment=DASHBOARD_ENV=prod" in _text(MONITOR_UNIT)
    assert "RUN_DASHBOARD_DB_MODE=service" in monitor
    assert "RUN_DASHBOARD_DB_SERVICE=REPLACE_WITH_MONITOR_LIBPQ_SERVICE" in monitor
    assert "RUN_DASHBOARD_DB_PASSFILE=/etc/brerc/production/monitor/monitor.pgpass" in monitor
    assert "RUN_DASHBOARD_EXPECTED_DATABASE=REPLACE_WITH_" in monitor
    assert "RUN_DASHBOARD_EXPECTED_ROLE=REPLACE_WITH_" in monitor
    assert "RUN_DASHBOARD_DATABASE_URL" not in monitor
    assert "DASHBOARD_USERNAME=" not in monitor
    assert "DASHBOARD_PASSWORD=" not in monitor
    assert "DASHBOARD_SECRET_KEY=" not in monitor


def test_libpq_profiles_are_credential_free_and_role_separated() -> None:
    api_profile = _text(PRODUCTION / "api-pg-service.conf.example")
    monitor_profile = _text(PRODUCTION / "monitor-pg-service.conf.example")
    combined = api_profile + monitor_profile
    assert "password=" not in combined.lower()
    assert "postgresql://" not in combined.lower()
    assert "REPLACE_WITH_PRIVATE_POSTGRES_HOSTNAME" in api_profile
    assert "REPLACE_WITH_PRIVATE_POSTGRES_HOSTNAME" in monitor_profile
    assert "user=REPLACE_WITH_API_LOGIN_ROLE" in api_profile
    assert "user=REPLACE_WITH_MONITOR_LOGIN_ROLE" in monitor_profile
    assert "MONITOR_LOGIN_ROLE" not in api_profile
    assert "API_LOGIN_ROLE" not in monitor_profile


def test_runbook_covers_target_host_rehearsal_and_recovery_boundaries() -> None:
    runbook = " ".join(_text(README).split())
    for required in (
        "same public origin",
        "systemd-analyze verify",
        "systemd-analyze security",
        "nginx -t",
        "ss -lntp",
        "browser mocks are absent",
        "one-time real `initial` load",
        "complete-snapshot `refresh`",
        "actual hardened units",
        "Never repoint a mutable symlink",
        "failed `refresh` must leave the previous active release visible",
        "target Linux host",
        "REPLACE_WITH_APPROVED_BASEMAP_ORIGIN",
        "browser CSP violation",
    ):
        assert required in runbook

    lower = runbook.lower()
    assert "root `docker-compose.yml`" in runbook
    assert "old root `Caddyfile`" in runbook
    assert "not a production deployment" in lower
    assert "does not publish martin" in lower


def test_legacy_root_stack_is_unambiguously_excluded_from_production() -> None:
    compose = _text(ROOT_COMPOSE)
    caddy = _text(ROOT_CADDY)
    assert compose.startswith(
        "# =============================================================================\n"
        "# ARCHIVED LEGACY DEMONSTRATION \u2014 NOT A SUPPORTED DEPLOYMENT OR ACCEPTANCE PATH."
    )
    assert "deploy/production/" in compose
    assert compose.count('profiles: ["legacy-obsolete"]') == 4
    assert "normal\n# `docker compose up` selects no service" in compose
    assert "APP_ENV: ${APP_ENV:-prod}" not in compose
    assert caddy.startswith("# ARCHIVED LEGACY PLACEHOLDER \u2014 NOT A PRODUCTION REVERSE PROXY.")
    assert "deploy/production/" in caddy


def test_libpq_password_files_are_private_and_readable_by_each_service() -> None:
    runbook = " ".join(_text(README).split())
    assert "api.pgpass`, owned by `brerc-api:brerc-api` mode `0600`" in runbook
    assert "monitor.pgpass`, owned by `brerc-monitor-ui:brerc-monitor-ui` mode `0600`" in runbook
    assert "libpq ignores insecure password files on Unix" in runbook


def test_target_linux_record_cannot_treat_missing_evidence_as_approval() -> None:
    procedure = " ".join(_text(LINUX_ACCEPTANCE).split())
    record = _text(ACCEPTANCE_RECORD)
    assert "A blank or `TBD` gate is a failed gate" in procedure
    for required in (
        "Overall result (`PASS` or `FAIL`)",
        "systemd-analyze verify",
        "Wrong CA/hostname/database/environment/role negative tests",
        "Second start without new approval failed",
        "No-change refresh reused the active release",
        "Failure invoked quarantine",
        "Prior immutable code/proxy artifact rollback rehearsed",
        "BRERC service owner/operator",
        "Delivery-team technical reviewer",
    ):
        assert required in record


def test_runtime_login_audit_checks_identity_membership_ownership_and_acl() -> None:
    sql = _text(RUNTIME_LOGIN_AUDIT)
    for required in (
        "current_database() <> expected_database",
        "rolsuper",
        "rolcreatedb",
        "rolcreaterole",
        "rolreplication",
        "rolbypassrls",
        "default_transaction_read_only=on",
        "pg_has_role(login_oid, role.oid, 'USAGE')",
        "membership.admin_option",
        "NOT membership.inherit_option",
        "runtime login has unsafe membership options",
        "runtime login owns a database object",
        "runtime login has a direct or default object grant",
        "runtime login audit passed",
    ):
        assert required in sql
