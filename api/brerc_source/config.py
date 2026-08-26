"""Strict, redacted configuration for the trusted PostgreSQL source adapter.

The repository template contains *names* of environment variables, never their
values.  This module resolves those names at startup but keeps the resulting
connection details out of object representations and error messages.

Configuration cannot approve a source.  In particular, ``source_environment``
is an independently pinned comparison label; it is not evidence that a BRERC
approval is authentic or that the connected database is the approved one.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from etl.pipeline import ColumnMap
from etl.source_contract import BRERC_MAIN_DATA_DASH, SourceContract

MAX_CONFIG_BYTES = 128 * 1024
BRERC_SOURCE_APPLICATION_NAME = "brerc-dashboard-source-connector"
ENV_NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{1,127}\Z")
ENVIRONMENT_LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
SERVICE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

ROOT_KEYS = frozenset(
    {
        "contract_version",
        "runtime",
        "connection",
        "source",
        "source_columns",
        "projection",
        "mapping",
        "incremental",
    }
)
RUNTIME_KEYS = frozenset(
    {
        "source_environment",
        "expected_database",
        "expected_role",
        "batch_size",
        "connect_timeout_seconds",
        "lock_timeout_ms",
        "statement_timeout_ms",
        "idle_in_transaction_session_timeout_ms",
        "total_timeout_seconds",
    }
)
SERVICE_CONNECTION_KEYS = frozenset(
    {
        "mode",
        "service_env",
        "service_file_env",
        "passfile_env",
        "sslrootcert_env",
        "sslmode",
    }
)
DIRECT_CONNECTION_KEYS = frozenset(
    {
        "mode",
        "host_env",
        "port_env",
        "database_env",
        "user_env",
        "passfile_env",
        "sslrootcert_env",
        "sslmode",
    }
)
SOURCE_KEYS = frozenset({"engine", "schema", "object", "object_type", "strict_schema"})
INCREMENTAL_KEYS = frozenset({"requested_modified_column", "status", "reason"})


class SourceConfigError(ValueError):
    """A deployment configuration is missing, unsafe or contract-incompatible."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Bounded controls for a single source-database operation."""

    source_environment: str = field(repr=False)
    expected_database: str = field(repr=False)
    expected_role: str = field(repr=False)
    batch_size: int
    connect_timeout_seconds: int
    lock_timeout_ms: int
    statement_timeout_ms: int
    idle_in_transaction_session_timeout_ms: int
    total_timeout_seconds: int

    def __post_init__(self) -> None:
        source_environment = _string(self.source_environment, "runtime.source_environment")
        if ENVIRONMENT_LABEL_PATTERN.fullmatch(source_environment) is None:
            raise SourceConfigError("runtime.source_environment is invalid")
        _string(self.expected_database, "runtime.expected_database")
        _string(self.expected_role, "runtime.expected_role")
        _integer(self.batch_size, "runtime.batch_size", 100, 100_000)
        _integer(
            self.connect_timeout_seconds,
            "runtime.connect_timeout_seconds",
            1,
            60,
        )
        _integer(self.lock_timeout_ms, "runtime.lock_timeout_ms", 100, 60_000)
        _integer(
            self.statement_timeout_ms,
            "runtime.statement_timeout_ms",
            1_000,
            3_600_000,
        )
        _integer(
            self.idle_in_transaction_session_timeout_ms,
            "runtime.idle_in_transaction_session_timeout_ms",
            1_000,
            300_000,
        )
        _integer(
            self.total_timeout_seconds,
            "runtime.total_timeout_seconds",
            60,
            86_400,
        )
        if self.statement_timeout_ms > self.total_timeout_seconds * 1_000:
            raise SourceConfigError("statement timeout cannot exceed the total operation timeout")


@dataclass(frozen=True)
class ConnectionConfig:
    """Resolved libpq parameters with a deliberately redacted representation."""

    mode: str
    sslmode: str
    connect_timeout_seconds: int
    _resolved_parameters: tuple[tuple[str, str | int], ...] = field(repr=False)
    # libpq reads this through the process-level PGSERVICEFILE setting. Psycopg
    # deliberately does not accept ``servicefile`` as a conninfo keyword.
    _service_file_path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"service", "direct"}:
            raise SourceConfigError("connection mode is invalid")
        if self.sslmode != "verify-full":
            raise SourceConfigError("connection TLS mode is invalid")
        _integer(
            self.connect_timeout_seconds,
            "connection.connect_timeout_seconds",
            1,
            60,
        )
        if not isinstance(self._resolved_parameters, tuple):
            raise SourceConfigError("resolved connection parameters are invalid")
        try:
            parameters = dict(self._resolved_parameters)
        except (TypeError, ValueError):
            raise SourceConfigError("resolved connection parameters are invalid") from None
        if len(parameters) != len(self._resolved_parameters):
            raise SourceConfigError("resolved connection parameters contain a duplicate key")
        common = (
            "passfile",
            "sslrootcert",
            "sslmode",
            "application_name",
            "connect_timeout",
        )
        if self.mode == "service":
            # Order is security-significant only for service expansion: later
            # explicit values must override weaker profile defaults.
            if tuple(parameters) != ("service", *common):
                raise SourceConfigError("resolved service parameters are not in the safe order")
        elif set(parameters) != {*common, "host", "port", "dbname", "user"}:
            raise SourceConfigError("resolved direct parameter names are invalid")
        if any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, str | int)
            or (
                isinstance(value, str)
                and (
                    not value
                    or value != value.strip()
                    or "\x00" in value
                    or "\n" in value
                    or "\r" in value
                )
            )
            for key, value in self._resolved_parameters
        ):
            raise SourceConfigError("resolved connection parameter values are invalid")
        if (
            parameters["sslmode"] != self.sslmode
            or parameters["application_name"] != BRERC_SOURCE_APPLICATION_NAME
            or parameters["connect_timeout"] != self.connect_timeout_seconds
        ):
            raise SourceConfigError("resolved connection safety controls are invalid")
        path_values = [parameters["passfile"], parameters["sslrootcert"]]
        if self.mode == "service":
            if not isinstance(self._service_file_path, str):
                raise SourceConfigError("resolved PostgreSQL service-file path is invalid")
            path_values.append(self._service_file_path)
            if SERVICE_NAME_PATTERN.fullmatch(str(parameters["service"])) is None:
                raise SourceConfigError("resolved PostgreSQL service name is invalid")
        else:
            if self._service_file_path is not None:
                raise SourceConfigError("direct connection cannot define a service file")
            host = str(parameters["host"])
            if (
                host.startswith("/")
                or any(character.isspace() for character in host)
                or any(fragment in host for fragment in ("/", "@", "?", "=", ","))
            ):
                raise SourceConfigError("resolved PostgreSQL host is not a TCP hostname")
            _integer(parameters["port"], "resolved PostgreSQL port", 1, 65_535)
        if any(not isinstance(path, str) or not Path(path).is_absolute() for path in path_values):
            raise SourceConfigError("resolved connection file paths must be absolute")
        if len(path_values) != len(set(path_values)):
            raise SourceConfigError("resolved connection file paths must be distinct")

    def __repr__(self) -> str:
        return (
            "ConnectionConfig("
            f"mode={self.mode!r}, sslmode={self.sslmode!r}, "
            f"connect_timeout_seconds={self.connect_timeout_seconds!r}, "
            "resolved_parameters=<redacted>)"
        )

    def parameters(self) -> dict[str, str | int]:
        """Return a fresh psycopg/libpq keyword mapping.

        Passwords and DSNs are never accepted, so neither can appear here.  The
        caller must also avoid logging this result.
        """
        return dict(self._resolved_parameters)

    def assert_process_environment(
        self,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """Bind service discovery to the path validated during config loading.

        ``PGSERVICEFILE`` is consumed by libpq from the live process rather
        than accepted as a Psycopg connection keyword. Rechecking immediately
        before connection prevents a missing or changed process value from
        silently selecting libpq's default service file. No environment value
        is included in the error.
        """
        process_environment = os.environ if environ is None else environ
        if process_environment.get("PGPASSWORD"):
            raise SourceConfigError("ambient PostgreSQL password configuration is not allowed")
        if self.mode != "service":
            return
        if process_environment.get("PGSERVICEFILE") != self._service_file_path:
            raise SourceConfigError("PostgreSQL service-file binding is invalid")


@dataclass(frozen=True)
class SourceLocation:
    engine: str
    schema: str
    object: str
    object_type: str
    strict_schema: bool

    def __post_init__(self) -> None:
        for label, value in (
            ("source.engine", self.engine),
            ("source.schema", self.schema),
            ("source.object", self.object),
            ("source.object_type", self.object_type),
        ):
            _string(value, label)
        if self.strict_schema is not True:
            raise SourceConfigError("source.strict_schema must be true")


@dataclass(frozen=True)
class SourceConnectorConfig:
    """Validated configuration bound to one reviewed source contract."""

    contract_version: str
    runtime: RuntimeConfig
    connection: ConnectionConfig
    source: SourceLocation
    source_columns: tuple[str, ...]
    projection: tuple[str, ...]
    column_map: ColumnMap

    def __post_init__(self) -> None:
        _string(self.contract_version, "contract_version")
        if not isinstance(self.runtime, RuntimeConfig):
            raise SourceConfigError("runtime configuration is invalid")
        if not isinstance(self.connection, ConnectionConfig):
            raise SourceConfigError("connection configuration is invalid")
        if not isinstance(self.source, SourceLocation):
            raise SourceConfigError("source configuration is invalid")
        if not isinstance(self.column_map, ColumnMap):
            raise SourceConfigError("pipeline column mapping is invalid")
        if self.connection.connect_timeout_seconds != self.runtime.connect_timeout_seconds:
            raise SourceConfigError("connection timeout disagrees with runtime controls")
        if self.connection.mode == "direct":
            parameters = self.connection.parameters()
            if (
                parameters["dbname"] != self.runtime.expected_database
                or parameters["user"] != self.runtime.expected_role
            ):
                raise SourceConfigError("direct connection differs from deployment assertions")
        if (
            not isinstance(self.source_columns, tuple)
            or not self.source_columns
            or any(not isinstance(name, str) or not name for name in self.source_columns)
            or len(set(self.source_columns)) != len(self.source_columns)
        ):
            raise SourceConfigError("source column manifest is invalid")
        if (
            not isinstance(self.projection, tuple)
            or any(not isinstance(name, str) or not name for name in self.projection)
            or len(set(self.projection)) != len(self.projection)
        ):
            raise SourceConfigError("projection is invalid")
        expected_projection = (*self.column_map.required(), *self.column_map.optional())
        if self.projection != expected_projection:
            raise SourceConfigError("projection disagrees with the pipeline mapping")
        if not set(self.projection).issubset(self.source_columns):
            raise SourceConfigError("projection references a column outside the source manifest")

    def __repr__(self) -> str:
        return (
            "SourceConnectorConfig("
            f"contract_version={self.contract_version!r}, "
            f"connection_mode={self.connection.mode!r}, "
            f"batch_size={self.runtime.batch_size!r}, "
            "resolved_environment=<redacted>)"
        )


def _load_yaml_module() -> Any:
    """Import PyYAML only when a connector configuration is actually loaded."""
    unavailable = False
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised without connector extra
        unavailable = True
    if unavailable:
        raise SourceConfigError(
            "connector configuration support is unavailable; install the "
            "connector-c or connector-binary package extra"
        )
    return yaml


def _parse_yaml(text: str) -> object:
    yaml = _load_yaml_module()
    parse_failed = False
    value: object = None
    try:
        # SafeLoader resolves aliases, so reject their syntax (and anchors and
        # explicit tags) before construction.  This keeps one plain data tree
        # whose meaning is visible in the file itself.
        for token in yaml.scan(text):
            if isinstance(token, yaml.tokens.AliasToken | yaml.tokens.AnchorToken):
                raise SourceConfigError("configuration aliases and anchors are not allowed")
            if isinstance(token, yaml.tokens.TagToken):
                raise SourceConfigError("configuration tags are not allowed")

        class UniqueSafeLoader(yaml.SafeLoader):
            pass

        # SafeLoader follows YAML 1.1 and would silently reinterpret values
        # such as ``yes``, ``ON``, timestamps, hexadecimal numbers and floats.
        # Connector configuration uses a deliberately smaller JSON-like scalar
        # vocabulary: exact lowercase booleans/null and canonical decimal
        # integers; every other unquoted scalar remains a string for the exact
        # field validators below.
        UniqueSafeLoader.yaml_implicit_resolvers = {}
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:bool",
            re.compile(r"^(?:true|false)$"),
            list("tf"),
        )
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:null",
            re.compile(r"^null$"),
            ["n"],
        )
        UniqueSafeLoader.add_implicit_resolver(
            "tag:yaml.org,2002:int",
            re.compile(r"^(?:0|-[1-9][0-9]*|[1-9][0-9]*)$"),
            list("-0123456789"),
        )

        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[str, object]:
            if not isinstance(node, yaml.MappingNode):
                raise SourceConfigError("configuration mapping is malformed")
            result: dict[str, object] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if not isinstance(key, str):
                    raise SourceConfigError("configuration keys must be strings")
                if key in result:
                    raise SourceConfigError("configuration contains a duplicate key")
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        UniqueSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        loader = UniqueSafeLoader(text)
        try:
            value = loader.get_single_data()
        finally:
            loader.dispose()
        return value
    except SourceConfigError:
        raise
    except yaml.YAMLError:
        # Scanner/parser exceptions may include input lines. Configuration is
        # credential-free by contract, but suppress raw input defensively.
        parse_failed = True
    if parse_failed:
        raise SourceConfigError("configuration is not valid restricted YAML")
    return value


def _strict_mapping(value: object, label: str, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SourceConfigError(f"{label} must be a mapping")
    actual = set(value)
    if actual != keys:
        raise SourceConfigError(f"{label} keys do not match the exact configuration schema")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\x00" in value:
        raise SourceConfigError(f"{label} must be a non-blank trimmed string")
    if "\n" in value or "\r" in value:
        raise SourceConfigError(f"{label} must be a single-line string")
    return value


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SourceConfigError(f"{label} must be an integer from {minimum} to {maximum}")
    return value


def _environment_name(value: object, label: str) -> str:
    name = _string(value, label)
    if ENV_NAME_PATTERN.fullmatch(name) is None:
        raise SourceConfigError(f"{label} must be an uppercase environment-variable name")
    if name == "PGPASSWORD":
        raise SourceConfigError("PGPASSWORD is not accepted; use a protected passfile")
    return name


def _resolve_environment(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise SourceConfigError(f"required environment variable {name} is missing or invalid")
    if value != value.strip() or "\n" in value or "\r" in value:
        raise SourceConfigError(f"required environment variable {name} is invalid")
    return value


def _resolve_path(name: str, environ: Mapping[str, str]) -> str:
    value = _resolve_environment(name, environ)
    if not Path(value).is_absolute():
        raise SourceConfigError(f"environment variable {name} must contain an absolute path")
    return value


def _parse_runtime(value: object) -> RuntimeConfig:
    raw = _strict_mapping(value, "runtime", RUNTIME_KEYS)
    source_environment = _string(raw["source_environment"], "runtime.source_environment")
    if ENVIRONMENT_LABEL_PATTERN.fullmatch(source_environment) is None:
        raise SourceConfigError(
            "runtime.source_environment must be a short letters/numbers/dot/dash label"
        )
    runtime = RuntimeConfig(
        source_environment=source_environment,
        expected_database=_string(raw["expected_database"], "runtime.expected_database"),
        expected_role=_string(raw["expected_role"], "runtime.expected_role"),
        batch_size=_integer(raw["batch_size"], "runtime.batch_size", 100, 100_000),
        connect_timeout_seconds=_integer(
            raw["connect_timeout_seconds"], "runtime.connect_timeout_seconds", 1, 60
        ),
        lock_timeout_ms=_integer(raw["lock_timeout_ms"], "runtime.lock_timeout_ms", 100, 60_000),
        statement_timeout_ms=_integer(
            raw["statement_timeout_ms"], "runtime.statement_timeout_ms", 1_000, 3_600_000
        ),
        idle_in_transaction_session_timeout_ms=_integer(
            raw["idle_in_transaction_session_timeout_ms"],
            "runtime.idle_in_transaction_session_timeout_ms",
            1_000,
            300_000,
        ),
        total_timeout_seconds=_integer(
            raw["total_timeout_seconds"], "runtime.total_timeout_seconds", 60, 86_400
        ),
    )
    if runtime.statement_timeout_ms > runtime.total_timeout_seconds * 1_000:
        raise SourceConfigError("statement timeout cannot exceed the total operation timeout")
    return runtime


def _parse_connection(
    value: object,
    runtime: RuntimeConfig,
    environ: Mapping[str, str],
) -> ConnectionConfig:
    if environ.get("PGPASSWORD"):
        raise SourceConfigError("ambient PostgreSQL password configuration is not allowed")
    if not isinstance(value, dict):
        raise SourceConfigError("connection must be a mapping")
    mode = value.get("mode")
    expected_keys = (
        SERVICE_CONNECTION_KEYS
        if mode == "service"
        else DIRECT_CONNECTION_KEYS
        if mode == "direct"
        else None
    )
    if expected_keys is None:
        raise SourceConfigError("connection.mode must be exactly 'service' or 'direct'")
    raw = _strict_mapping(value, "connection", expected_keys)
    if raw["sslmode"] != "verify-full":
        raise SourceConfigError("connection.sslmode must be exactly 'verify-full'")

    passfile_name = _environment_name(raw["passfile_env"], "connection.passfile_env")
    rootcert_name = _environment_name(raw["sslrootcert_env"], "connection.sslrootcert_env")
    safety_parameters: dict[str, str | int] = {
        "passfile": _resolve_path(passfile_name, environ),
        "sslrootcert": _resolve_path(rootcert_name, environ),
        "sslmode": "verify-full",
        "application_name": BRERC_SOURCE_APPLICATION_NAME,
        "connect_timeout": runtime.connect_timeout_seconds,
    }
    if safety_parameters["passfile"] == safety_parameters["sslrootcert"]:
        raise SourceConfigError("connector security files must use distinct paths")
    if mode == "service":
        service_name = _environment_name(raw["service_env"], "connection.service_env")
        service_file_name = _environment_name(
            raw["service_file_env"], "connection.service_file_env"
        )
        if service_file_name != "PGSERVICEFILE":
            raise SourceConfigError("connection.service_file_env must be exactly PGSERVICEFILE")
        service = _resolve_environment(service_name, environ)
        if SERVICE_NAME_PATTERN.fullmatch(service) is None:
            raise SourceConfigError("the resolved PostgreSQL service name is invalid")
        servicefile = _resolve_path(service_file_name, environ)
        if servicefile in {
            safety_parameters["passfile"],
            safety_parameters["sslrootcert"],
        }:
            raise SourceConfigError("connector security files must use distinct paths")
        # libpq expands a service profile and then applies later explicit
        # conninfo values. Keep the selector first so the connector's mandatory
        # TLS, CA, passfile, application name and timeout always win.
        parameters: dict[str, str | int] = {
            "service": service,
            **safety_parameters,
        }
    else:
        environment_names = {
            key: _environment_name(raw[f"{key}_env"], f"connection.{key}_env")
            for key in ("host", "port", "database", "user")
        }
        port_name = environment_names["port"]
        port_value = _resolve_environment(port_name, environ)
        if not port_value.isascii() or not port_value.isdecimal():
            raise SourceConfigError(f"environment variable {port_name} must contain a TCP port")
        port = int(port_value)
        if not 1 <= port <= 65_535:
            raise SourceConfigError(f"environment variable {port_name} must contain a TCP port")
        host = _resolve_environment(environment_names["host"], environ)
        if (
            host.startswith("/")
            or any(character.isspace() for character in host)
            or any(fragment in host for fragment in ("/", "@", "?", "=", ","))
        ):
            raise SourceConfigError("the direct connection host must be a TCP hostname")
        parameters = {
            **safety_parameters,
            "host": host,
            "port": port,
            "dbname": _resolve_environment(environment_names["database"], environ),
            "user": _resolve_environment(environment_names["user"], environ),
        }
        if (
            parameters["dbname"] != runtime.expected_database
            or parameters["user"] != runtime.expected_role
        ):
            raise SourceConfigError(
                "direct connection database or role differs from its deployment assertion"
            )
    return ConnectionConfig(
        mode=mode,
        sslmode="verify-full",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
        _resolved_parameters=tuple(parameters.items()),
        _service_file_path=servicefile if mode == "service" else None,
    )


def _parse_column_map(value: object, contract: SourceContract) -> ColumnMap:
    expected_mapping = dict(contract.pipeline_mapping)
    raw = _strict_mapping(value, "mapping", frozenset(expected_mapping))
    if raw != expected_mapping:
        raise SourceConfigError("mapping does not exactly match the reviewed source contract")
    mapping_failed = False
    try:
        column_map = ColumnMap(**raw)
    except (TypeError, ValueError):  # defensive: contract owns the exact keys
        mapping_failed = True
    if mapping_failed:
        raise SourceConfigError("mapping cannot construct the reviewed pipeline mapping")
    return column_map


def load_source_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
    contract: SourceContract = BRERC_MAIN_DATA_DASH,
) -> SourceConnectorConfig:
    """Load one exact, credential-free connector configuration.

    Environment values are resolved once into a redacted connection object.
    They are deployment inputs only and cannot satisfy view or publication
    approval requirements.
    """
    if not isinstance(path, str | Path):
        raise SourceConfigError("configuration path is invalid")
    config_path = Path(path)
    inspect_failed = False
    try:
        size = config_path.stat().st_size
    except OSError:
        inspect_failed = True
        size = 0
    if inspect_failed:
        raise SourceConfigError("configuration file cannot be inspected")
    if not 1 <= size <= MAX_CONFIG_BYTES:
        raise SourceConfigError(
            f"configuration file size must be between 1 and {MAX_CONFIG_BYTES} bytes"
        )
    read_failed = False
    try:
        raw_bytes = config_path.read_bytes()
    except OSError:
        read_failed = True
        raw_bytes = b""
    if read_failed:
        raise SourceConfigError("configuration file is not readable strict UTF-8")
    if not 1 <= len(raw_bytes) <= MAX_CONFIG_BYTES:
        # Recheck the bytes actually parsed so a file replacement between stat
        # and read cannot bypass the resource bound.
        raise SourceConfigError(
            f"configuration file size must be between 1 and {MAX_CONFIG_BYTES} bytes"
        )
    decode_failed = False
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeError:
        decode_failed = True
        text = ""
    if decode_failed:
        raise SourceConfigError("configuration file is not readable strict UTF-8")
    document = _strict_mapping(_parse_yaml(text), "configuration", ROOT_KEYS)

    contract_version = _string(document["contract_version"], "contract_version")
    if contract_version != contract.version:
        raise SourceConfigError("contract_version does not match the reviewed source contract")

    runtime = _parse_runtime(document["runtime"])
    resolved_environ: Mapping[str, str] = os.environ if environ is None else environ
    connection = _parse_connection(document["connection"], runtime, resolved_environ)

    source_raw = _strict_mapping(document["source"], "source", SOURCE_KEYS)
    expected_source = {
        "engine": "postgresql",
        "schema": contract.schema,
        "object": contract.name,
        "object_type": contract.object_type,
        "strict_schema": True,
    }
    if source_raw != expected_source:
        raise SourceConfigError("source does not exactly match the reviewed PostgreSQL view")

    expected_columns = tuple(column.name for column in contract.columns)
    source_columns = document["source_columns"]
    if not isinstance(source_columns, list) or any(
        not isinstance(column, str) for column in source_columns
    ):
        raise SourceConfigError("source_columns must be an ordered list of strings")
    if tuple(source_columns) != expected_columns:
        raise SourceConfigError("source_columns do not exactly match the reviewed source contract")

    expected_projection = tuple(
        source for _, source in contract.pipeline_mapping if source is not None
    )
    projection = document["projection"]
    if not isinstance(projection, list) or any(
        not isinstance(column, str) for column in projection
    ):
        raise SourceConfigError("projection must be an ordered list of strings")
    if tuple(projection) != expected_projection:
        raise SourceConfigError("projection does not exactly match the reviewed safe projection")

    column_map = _parse_column_map(document["mapping"], contract)
    incremental = _strict_mapping(document["incremental"], "incremental", INCREMENTAL_KEYS)
    expected_incremental = {
        "requested_modified_column": "date_mdb_modified",
        "status": "blocked",
        "reason": "requires-a-new-versioned-source-contract-and-loader",
    }
    if incremental != expected_incremental:
        raise SourceConfigError("incremental settings must remain at the reviewed blocked state")

    return SourceConnectorConfig(
        contract_version=contract_version,
        runtime=runtime,
        connection=connection,
        source=SourceLocation(**source_raw),
        source_columns=tuple(source_columns),
        projection=tuple(projection),
        column_map=column_map,
    )
