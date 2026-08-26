"""Strict, redacted configuration for the notification worker.

The tracked YAML contains only environment-variable *names*.  Database and
provider credentials are read from absolute, protected file paths supplied by
the deployment secret store.  No DSN, password, webhook key or recipient is
ever included in a representation or configuration error.
"""

from __future__ import annotations

import configparser
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import NotifierConfigurationError

CONFIG_VERSION = "brerc-notifier-v1"
APPLICATION_NAME = "brerc-dashboard-notifier"
MAX_CONFIG_BYTES = 128 * 1024
MAX_SECRET_BYTES = 16 * 1024
MAX_PROTECTED_FILE_BYTES = 1024 * 1024

_ENVIRONMENT_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,127}\Z")
_SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_DATABASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}\Z")
_HOSTNAME = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z"
)
_EMAIL = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}\Z"
)

_ROOT_KEYS = frozenset({"config_version", "database", "runtime", "destinations"})
_DATABASE_KEYS = frozenset(
    {
        "expected_database",
        "expected_login",
        "expected_role",
        "expected_migration_version",
        "connect_timeout_seconds",
        "statement_timeout_ms",
        "service_env",
        "service_file_env",
        "passfile_env",
        "sslrootcert_env",
        "sslmode",
    }
)
_RUNTIME_KEYS = frozenset(
    {
        "batch_size",
        "lease_seconds",
        "poll_interval_seconds",
        "delivery_timeout_seconds",
        "provider_probe_interval_seconds",
        "readiness_stale_seconds",
        "health_host",
        "health_port",
    }
)
_SMTP_KEYS = frozenset(
    {
        "provider",
        "host",
        "port",
        "from_address",
        "to_addresses",
        "username_file_env",
        "password_file_env",
    }
)
_WEBHOOK_KEYS = frozenset({"provider", "url", "secret_file_env"})


def _invalid() -> NotifierConfigurationError:
    return NotifierConfigurationError()


def _text(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\r" in value
        or "\n" in value
    ):
        raise _invalid()
    return value


def _integer(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid()
    return value


def _strict_mapping(value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _invalid()
    return value


def _environment_name(value: object) -> str:
    name = _text(value)
    if _ENVIRONMENT_NAME.fullmatch(name) is None or name == "PGPASSWORD":
        raise _invalid()
    return name


def _resolved(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\r" in value
        or "\n" in value
        or len(value.encode("utf-8")) > MAX_SECRET_BYTES
    ):
        raise _invalid()
    return value


def _resolved_path(name: str, environ: Mapping[str, str]) -> Path:
    path = Path(_resolved(name, environ))
    if not path.is_absolute():
        raise _invalid()
    return path


def _protected_file(path: Path, *, maximum: int) -> os.stat_result:
    """Require a bounded regular file with no group/other access."""

    try:
        details = path.lstat()
    except OSError:
        raise _invalid() from None
    if (
        not stat.S_ISREG(details.st_mode)
        or stat.S_IMODE(details.st_mode) & 0o077
        or not 1 <= details.st_size <= maximum
    ):
        raise _invalid()
    return details


def _secret_bytes(path: Path, *, minimum: int = 1) -> bytes:
    try:
        size = _protected_file(path, maximum=MAX_SECRET_BYTES).st_size
        value = path.read_bytes()
    except OSError:
        raise _invalid() from None
    if size != len(value) or not minimum <= len(value) <= MAX_SECRET_BYTES:
        raise _invalid()
    if b"\x00" in value or b"\r" in value or b"\n" in value:
        raise _invalid()
    return value


def _validate_service_file(
    path: Path,
    service: str,
    expected_database: str,
    expected_login: str,
) -> tuple[str, int, str, str]:
    """Accept one deterministic, password-free libpq service definition."""

    try:
        expected_size = _protected_file(path, maximum=MAX_PROTECTED_FILE_BYTES).st_size
        raw = path.read_bytes()
        if len(raw) != expected_size or b"\x00" in raw:
            raise _invalid()
        text = raw.decode("utf-8")
        parser = configparser.RawConfigParser(
            interpolation=None,
            strict=True,
            delimiters=("=",),
            comment_prefixes=("#", ";"),
            inline_comment_prefixes=None,
            empty_lines_in_values=False,
        )
        parser.optionxform = str.lower
        parser.read_string(text)
        if parser.sections() != [service]:
            raise _invalid()
        section = parser[service]
        if set(section) != {"host", "port", "dbname", "user", "sslmode"}:
            raise _invalid()
        if section["sslmode"] != "verify-full":
            raise _invalid()
        if _HOSTNAME.fullmatch(_text(section["host"])) is None:
            raise _invalid()
        port = section["port"]
        if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65_535:
            raise _invalid()
        if (
            _text(section["dbname"]) != expected_database
            or _text(section["user"]) != expected_login
        ):
            raise _invalid()
        return (
            section["host"],
            int(port),
            section["dbname"],
            section["user"],
        )
    except NotifierConfigurationError:
        raise
    except (configparser.Error, OSError, UnicodeError, ValueError):
        raise _invalid() from None


def _split_passfile_entry(line: str) -> tuple[str, str, str, str, str]:
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            if character not in {":", "\\"}:
                raise _invalid()
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        raise _invalid()
    fields.append("".join(current))
    if len(fields) != 5:
        raise _invalid()
    return fields[0], fields[1], fields[2], fields[3], fields[4]


def _validate_passfile(
    path: Path,
    expected_connection: tuple[str, int, str, str],
) -> None:
    """Require one exact notifier entry and no wildcard/admin credential."""

    try:
        expected_size = _protected_file(path, maximum=MAX_SECRET_BYTES).st_size
        raw = path.read_bytes()
        if len(raw) != expected_size or b"\x00" in raw or b"\r" in raw:
            raise _invalid()
        text = raw.decode("utf-8")
        if text.endswith("\n"):
            text = text[:-1]
        if not text or "\n" in text:
            raise _invalid()
        host, port, database, login, password = _split_passfile_entry(text)
        expected_host, expected_port, expected_database, expected_login = expected_connection
        if (
            host != expected_host
            or port != str(expected_port)
            or database != expected_database
            or login != expected_login
            or not password
        ):
            raise _invalid()
    except NotifierConfigurationError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise _invalid() from None


def _secret_text(path: Path) -> str:
    try:
        value = _secret_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        raise _invalid() from None
    if value != value.strip():
        raise _invalid()
    return value


def _restricted_yaml(text: str) -> object:
    try:
        import yaml

        for token in yaml.scan(text):
            if isinstance(token, yaml.tokens.AliasToken | yaml.tokens.AnchorToken):
                raise _invalid()
            if isinstance(token, yaml.tokens.TagToken):
                raise _invalid()

        class UniqueSafeLoader(yaml.SafeLoader):
            pass

        UniqueSafeLoader.yaml_implicit_resolvers = {}
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
        )
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:null", re.compile(r"^null$"), ["n"]
        )
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:int", re.compile(r"^(?:0|-?[1-9][0-9]*)$"), list("-0123456789")
        )

        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[object, object]:
            result: dict[object, object] = {}
            for key, value in loader.construct_pairs(node, deep=deep):
                if not isinstance(key, str) or key in result:
                    raise _invalid()
                result[key] = value
            return result

        UniqueSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
        )
        loader = UniqueSafeLoader(text)
        try:
            return loader.get_single_data()
        finally:
            loader.dispose()
    except NotifierConfigurationError:
        raise
    except Exception:
        raise _invalid() from None


@dataclass(frozen=True)
class DatabaseConfig:
    expected_database: str = field(repr=False)
    expected_login: str = field(repr=False)
    expected_role: str
    expected_migration_version: int
    connect_timeout_seconds: int
    statement_timeout_ms: int
    _service: str = field(repr=False)
    _service_file: Path = field(repr=False)
    _passfile: Path = field(repr=False)
    _sslrootcert: Path = field(repr=False)

    def parameters(self) -> dict[str, str | int]:
        return {
            "service": self._service,
            "passfile": str(self._passfile),
            "sslrootcert": str(self._sslrootcert),
            "sslmode": "verify-full",
            "application_name": APPLICATION_NAME,
            "connect_timeout": self.connect_timeout_seconds,
            "options": f"-c statement_timeout={self.statement_timeout_ms}",
        }

    def assert_process_environment(self, environ: Mapping[str, str] | None = None) -> None:
        process = os.environ if environ is None else environ
        if "PGPASSWORD" in process or process.get("PGSERVICEFILE") != str(self._service_file):
            raise _invalid()

    def __repr__(self) -> str:
        return (
            "DatabaseConfig(expected_role='brerc_notifier', "
            f"migration={self.expected_migration_version}, connection=<redacted>)"
        )


@dataclass(frozen=True)
class RuntimeConfig:
    batch_size: int
    lease_seconds: int
    poll_interval_seconds: int
    delivery_timeout_seconds: int
    provider_probe_interval_seconds: int
    readiness_stale_seconds: int
    health_host: str
    health_port: int


@dataclass(frozen=True)
class SmtpDestination:
    provider: str
    host: str = field(repr=False)
    port: int
    from_address: str = field(repr=False)
    to_addresses: tuple[str, ...] = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)

    def __repr__(self) -> str:
        return "SmtpDestination(provider='smtp', endpoint=<redacted>, credentials=<redacted>)"


@dataclass(frozen=True)
class WebhookDestination:
    provider: str
    url: str = field(repr=False)
    secret: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "WebhookDestination(provider='webhook', endpoint=<redacted>, secret=<redacted>)"


Destination = SmtpDestination | WebhookDestination


@dataclass(frozen=True)
class NotifierConfig:
    version: str
    database: DatabaseConfig
    runtime: RuntimeConfig
    destinations: Mapping[str, Destination] = field(repr=False)

    def __repr__(self) -> str:
        providers = tuple(sorted(destination.provider for destination in self.destinations.values()))
        return (
            f"NotifierConfig(version={self.version!r}, providers={providers!r}, "
            "database=<redacted>, destinations=<redacted>)"
        )


def _parse_database(value: object, environ: Mapping[str, str]) -> DatabaseConfig:
    if "PGPASSWORD" in environ:
        raise _invalid()
    raw = _strict_mapping(value, _DATABASE_KEYS)
    if raw["sslmode"] != "verify-full":
        raise _invalid()
    expected_database = _text(raw["expected_database"])
    expected_login = _text(raw["expected_login"])
    expected_role = _text(raw["expected_role"])
    if (
        _DATABASE_NAME.fullmatch(expected_database) is None
        or _DATABASE_NAME.fullmatch(expected_login) is None
        or expected_role != "brerc_notifier"
    ):
        raise _invalid()
    names = {
        key: _environment_name(raw[key])
        for key in ("service_env", "service_file_env", "passfile_env", "sslrootcert_env")
    }
    if names["service_file_env"] != "PGSERVICEFILE" or len(set(names.values())) != 4:
        raise _invalid()
    service = _resolved(names["service_env"], environ)
    if _SERVICE_NAME.fullmatch(service) is None:
        raise _invalid()
    service_file = _resolved_path(names["service_file_env"], environ)
    passfile = _resolved_path(names["passfile_env"], environ)
    rootcert = _resolved_path(names["sslrootcert_env"], environ)
    if len({service_file, passfile, rootcert}) != 3:
        raise _invalid()
    for path in (service_file, passfile, rootcert):
        _protected_file(path, maximum=MAX_PROTECTED_FILE_BYTES)
    expected_connection = _validate_service_file(
        service_file,
        service,
        expected_database,
        expected_login,
    )
    _validate_passfile(passfile, expected_connection)
    return DatabaseConfig(
        expected_database=expected_database,
        expected_login=expected_login,
        expected_role=expected_role,
        expected_migration_version=_integer(raw["expected_migration_version"], 2, 2),
        connect_timeout_seconds=_integer(raw["connect_timeout_seconds"], 1, 60),
        statement_timeout_ms=_integer(raw["statement_timeout_ms"], 100, 60_000),
        _service=service,
        _service_file=service_file,
        _passfile=passfile,
        _sslrootcert=rootcert,
    )


def _parse_runtime(value: object) -> RuntimeConfig:
    raw = _strict_mapping(value, _RUNTIME_KEYS)
    runtime = RuntimeConfig(
        # A single process delivers sequentially. Claiming more than one would
        # let later leases age while an earlier provider call is in flight.
        # Scale safely by running multiple workers; SKIP LOCKED coordinates them.
        batch_size=_integer(raw["batch_size"], 1, 1),
        lease_seconds=_integer(raw["lease_seconds"], 30, 900),
        poll_interval_seconds=_integer(raw["poll_interval_seconds"], 1, 300),
        delivery_timeout_seconds=_integer(raw["delivery_timeout_seconds"], 1, 60),
        provider_probe_interval_seconds=_integer(
            raw["provider_probe_interval_seconds"], 30, 3600
        ),
        readiness_stale_seconds=_integer(raw["readiness_stale_seconds"], 10, 3600),
        health_host=_text(raw["health_host"]),
        health_port=_integer(raw["health_port"], 1024, 65_535),
    )
    if (
        runtime.health_host not in {"0.0.0.0", "127.0.0.1"}
        or runtime.delivery_timeout_seconds * 4 >= runtime.lease_seconds
        or runtime.provider_probe_interval_seconds < runtime.poll_interval_seconds
        or runtime.readiness_stale_seconds < runtime.poll_interval_seconds * 3
    ):
        raise _invalid()
    return runtime


def _email(value: object) -> str:
    address = _text(value)
    if _EMAIL.fullmatch(address) is None:
        raise _invalid()
    return address


def _destination_secret_path(
    value: object,
    environ: Mapping[str, str],
    used_environment_names: set[str],
    used_paths: set[Path],
) -> Path:
    name = _environment_name(value)
    path = _resolved_path(name, environ)
    try:
        identity = path.resolve(strict=True)
    except OSError:
        raise _invalid() from None
    if name in used_environment_names or identity in used_paths:
        raise _invalid()
    used_environment_names.add(name)
    used_paths.add(identity)
    return path


def _parse_destination(
    value: object,
    environ: Mapping[str, str],
    used_environment_names: set[str],
    used_paths: set[Path],
) -> Destination:
    if not isinstance(value, dict):
        raise _invalid()
    provider = value.get("provider")
    if provider == "smtp":
        raw = _strict_mapping(value, _SMTP_KEYS)
        host = _text(raw["host"])
        if _HOSTNAME.fullmatch(host) is None:
            raise _invalid()
        recipients = raw["to_addresses"]
        if not isinstance(recipients, list) or len(recipients) != 1:
            raise _invalid()
        to_addresses = tuple(_email(item) for item in recipients)
        username_path = _destination_secret_path(
            raw["username_file_env"],
            environ,
            used_environment_names,
            used_paths,
        )
        password_path = _destination_secret_path(
            raw["password_file_env"],
            environ,
            used_environment_names,
            used_paths,
        )
        return SmtpDestination(
            provider="smtp",
            host=host,
            port=_integer(raw["port"], 1, 65_535),
            from_address=_email(raw["from_address"]),
            to_addresses=to_addresses,
            username=_secret_text(username_path),
            password=_secret_text(password_path),
        )
    if provider == "webhook":
        raw = _strict_mapping(value, _WEBHOOK_KEYS)
        url = _text(raw["url"])
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or _HOSTNAME.fullmatch(parsed.hostname) is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or not parsed.path.startswith("/")
        ):
            raise _invalid()
        try:
            port = parsed.port
        except ValueError:
            raise _invalid() from None
        if port is not None and not 1 <= port <= 65_535:
            raise _invalid()
        secret_path = _destination_secret_path(
            raw["secret_file_env"],
            environ,
            used_environment_names,
            used_paths,
        )
        return WebhookDestination(
            provider="webhook", url=url, secret=_secret_bytes(secret_path, minimum=32)
        )
    raise _invalid()


def load_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> NotifierConfig:
    """Load a complete notifier configuration or raise one content-free error."""

    config_path = Path(path)
    process = os.environ if environ is None else environ
    try:
        if not config_path.is_absolute():
            raise _invalid()
        _protected_file(config_path, maximum=MAX_CONFIG_BYTES)
        document = _restricted_yaml(config_path.read_text(encoding="utf-8"))
        root = _strict_mapping(document, _ROOT_KEYS)
        if root["config_version"] != CONFIG_VERSION:
            raise _invalid()
        raw_database = _strict_mapping(root["database"], _DATABASE_KEYS)
        database = _parse_database(raw_database, process)
        runtime = _parse_runtime(root["runtime"])
        database_operation_seconds = database.connect_timeout_seconds + (
            database.statement_timeout_ms + 999
        ) // 1000
        if database_operation_seconds * 4 >= runtime.lease_seconds:
            raise _invalid()
        used_environment_names = {
            _environment_name(raw_database[key])
            for key in ("service_env", "service_file_env", "passfile_env", "sslrootcert_env")
        }
        used_paths = {
            item.resolve(strict=True)
            for item in (
                config_path,
                database._service_file,
                database._passfile,
                database._sslrootcert,
            )
        }
        if len(used_paths) != 4:
            raise _invalid()
        raw_destinations = root["destinations"]
        if not isinstance(raw_destinations, dict) or set(raw_destinations) != {
            "etl-operations"
        }:
            raise _invalid()
        destinations: dict[str, Destination] = {}
        for raw_key, raw_value in raw_destinations.items():
            key = _text(raw_key)
            if _IDENTIFIER.fullmatch(key) is None:
                raise _invalid()
            destinations[key] = _parse_destination(
                raw_value,
                process,
                used_environment_names,
                used_paths,
            )
        return NotifierConfig(
            version=CONFIG_VERSION,
            database=database,
            runtime=runtime,
            destinations=destinations,
        )
    except NotifierConfigurationError:
        raise
    except (OSError, UnicodeError, TypeError, ValueError):
        raise _invalid() from None
