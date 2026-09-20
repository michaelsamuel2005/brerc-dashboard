"""Strict, redacted configuration for the BRERC source-to-public loader.

This package deliberately owns target write credentials separately from the
read-only source connector. Credentials and HMAC keys are referenced only by
environment-variable name. Resolved values are never included in
representations or validation errors.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from .errors import LoaderConfigurationError

LOADER_CONFIG_VERSION = "brerc-loader-v3"
BRERC_TARGET_APPLICATION_NAME = "brerc-dashboard-release-loader"
MAX_CONFIG_BYTES = 128 * 1024
MAX_ENV_VALUE_BYTES = 4096
MAX_PUBLICATION_POLICY_BYTES = 1024 * 1024
MAX_SPECIES_DICTIONARY_BYTES = 128 * 1024 * 1024
MIN_RECONCILIATION_SECRET_BYTES = 32

_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{1,127}\Z")
_SERVICE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

_ROOT_KEYS = frozenset(
    {
        "loader_config_version",
        "publication",
        "species_dictionary",
        "source_config_path",
        "runtime",
        "target_connection",
        "reconciliation",
    }
)
_RUNTIME_KEYS = frozenset(
    {
        "expected_target_database",
        "expected_target_environment_id",
        "expected_target_role",
        "batch_size",
        "connect_timeout_seconds",
        "initial_max_source_rows",
        "initial_min_source_rows",
        "refresh_max_source_rows",
        "refresh_min_source_rows",
        "refresh_max_source_row_drop_bps",
        "refresh_max_source_row_growth_bps",
        "refresh_max_publication_basis_drop_bps",
        "refresh_max_species_drop_bps",
        "refresh_max_cell_drop_bps",
        "refresh_max_species_year_drop_bps",
        "lock_timeout_ms",
        "statement_timeout_ms",
        "total_timeout_seconds",
    }
)
_SERVICE_CONNECTION_KEYS = frozenset(
    {
        "mode",
        "service_env",
        "service_file_env",
        "passfile_env",
        "sslrootcert_env",
        "sslmode",
    }
)
_DIRECT_CONNECTION_KEYS = frozenset(
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
_RECONCILIATION_KEYS = frozenset({"secret_env"})
_PUBLICATION_KEYS = frozenset({"policy_path", "expected_sha256", "public_id_secret_env"})
_SPECIES_DICTIONARY_KEYS = frozenset({"csv_path", "expected_raw_sha256"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _invalid() -> LoaderConfigurationError:
    """Return one content-free exception suitable for crossing the boundary."""
    return LoaderConfigurationError()


def _string(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\n" in value
        or "\r" in value
    ):
        raise _invalid()
    return value


def _uuid(value: object) -> UUID:
    text = _string(value)
    try:
        parsed = UUID(text)
    except (AttributeError, TypeError, ValueError):
        raise _invalid() from None
    if parsed.int == 0 or str(parsed) != text:
        raise _invalid()
    return parsed


def _integer(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _invalid()
    return value


def _environment_name(value: object) -> str:
    name = _string(value)
    if _ENV_NAME.fullmatch(name) is None or name == "PGPASSWORD":
        raise _invalid()
    return name


def _resolved(name: str, environ: Mapping[str, str]) -> str:
    value = environ.get(name)
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
        or "\n" in value
        or "\r" in value
        or len(value.encode("utf-8")) > MAX_ENV_VALUE_BYTES
    ):
        raise _invalid()
    return value


def _resolved_path(name: str, environ: Mapping[str, str]) -> str:
    value = _resolved(name, environ)
    if not Path(value).is_absolute():
        raise _invalid()
    return value


def _sha256(value: object) -> str:
    digest = _string(value)
    if _SHA256.fullmatch(digest) is None:
        raise _invalid()
    return digest


def _publication_policy_artifact(path: Path, expected_sha256: str) -> bytes:
    """Read and bind one opaque policy snapshot without interpreting its JSON."""
    if not path.is_absolute() or path.suffix != ".json":
        raise _invalid()
    try:
        size = path.stat().st_size
    except OSError:
        raise _invalid() from None
    if not 1 <= size <= MAX_PUBLICATION_POLICY_BYTES:
        raise _invalid()
    try:
        artifact = path.read_bytes()
    except OSError:
        raise _invalid() from None
    if not 1 <= len(artifact) <= MAX_PUBLICATION_POLICY_BYTES:
        raise _invalid()
    actual_sha256 = hashlib.sha256(artifact).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_sha256):
        raise _invalid()
    return artifact


def _species_dictionary_artifact(path: Path, expected_raw_sha256: str) -> bytes:
    """Read and bind one bounded species-dictionary snapshot."""
    if not path.is_absolute() or path.suffix != ".csv":
        raise _invalid()
    try:
        with path.open("rb") as handle:
            artifact = handle.read(MAX_SPECIES_DICTIONARY_BYTES + 1)
    except OSError:
        raise _invalid() from None
    if not 1 <= len(artifact) <= MAX_SPECIES_DICTIONARY_BYTES:
        raise _invalid()
    actual_sha256 = hashlib.sha256(artifact).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_raw_sha256):
        raise _invalid()
    return artifact


def _strict_mapping(value: object, keys: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _invalid()
    return value


def _load_yaml_module() -> Any:
    try:
        import yaml
    except ImportError:
        raise _invalid() from None
    return yaml


def _restricted_yaml(text: str) -> object:
    """Parse one plain JSON-like YAML document with no hidden merge behaviour."""
    yaml = _load_yaml_module()
    try:
        for token in yaml.scan(text):
            if isinstance(token, yaml.tokens.AliasToken | yaml.tokens.AnchorToken):
                raise _invalid()
            if isinstance(token, yaml.tokens.TagToken):
                raise _invalid()

        class UniqueSafeLoader(yaml.SafeLoader):
            pass

        # YAML 1.1 coercions such as yes/ON, dates, floats and hexadecimal
        # numbers are too surprising for an operational security file.
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
            re.compile(r"^(?:0|-?[1-9][0-9]*)$"),
            list("-0123456789"),
        )

        def construct_mapping(
            loader: object, node: object, deep: bool = False
        ) -> dict[object, object]:
            pairs = loader.construct_pairs(node, deep=deep)
            result: dict[object, object] = {}
            for key, value in pairs:
                if not isinstance(key, str) or key in result:
                    raise _invalid()
                result[key] = value
            return result

        UniqueSafeLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        loader = UniqueSafeLoader(text)
        try:
            document = loader.get_single_data()
        finally:
            loader.dispose()
        return document
    except LoaderConfigurationError:
        raise
    except (yaml.YAMLError, UnicodeError, TypeError, ValueError):
        raise _invalid() from None


@dataclass(frozen=True)
class LoaderRuntimeConfig:
    """Finite resource and target-identity controls for one load."""

    expected_target_database: str = field(repr=False)
    expected_target_environment_id: UUID = field(repr=False)
    expected_target_role: str = field(repr=False)
    batch_size: int
    initial_min_source_rows: int
    initial_max_source_rows: int
    refresh_min_source_rows: int
    refresh_max_source_rows: int
    refresh_max_source_row_drop_bps: int
    refresh_max_source_row_growth_bps: int
    refresh_max_publication_basis_drop_bps: int
    refresh_max_species_drop_bps: int
    refresh_max_cell_drop_bps: int
    refresh_max_species_year_drop_bps: int
    connect_timeout_seconds: int
    lock_timeout_ms: int
    statement_timeout_ms: int
    total_timeout_seconds: int

    def __post_init__(self) -> None:
        _string(self.expected_target_database)
        if (
            type(self.expected_target_environment_id) is not UUID
            or self.expected_target_environment_id.int == 0
        ):
            raise _invalid()
        _string(self.expected_target_role)
        _integer(self.batch_size, 100, 100_000)
        _integer(self.initial_min_source_rows, 1, 1_000_000_000)
        _integer(self.initial_max_source_rows, 1, 1_000_000_000)
        if self.initial_min_source_rows > self.initial_max_source_rows:
            raise _invalid()
        _integer(self.refresh_min_source_rows, 1, 1_000_000_000)
        _integer(self.refresh_max_source_rows, 1, 1_000_000_000)
        if self.refresh_min_source_rows > self.refresh_max_source_rows:
            raise _invalid()
        _integer(self.refresh_max_source_row_drop_bps, 0, 10_000)
        _integer(self.refresh_max_source_row_growth_bps, 0, 1_000_000_000)
        _integer(self.refresh_max_publication_basis_drop_bps, 0, 10_000)
        _integer(self.refresh_max_species_drop_bps, 0, 10_000)
        _integer(self.refresh_max_cell_drop_bps, 0, 10_000)
        _integer(self.refresh_max_species_year_drop_bps, 0, 10_000)
        _integer(self.connect_timeout_seconds, 1, 60)
        _integer(self.lock_timeout_ms, 100, 60_000)
        _integer(self.statement_timeout_ms, 1_000, 3_600_000)
        _integer(self.total_timeout_seconds, 60, 86_400)
        if self.statement_timeout_ms > self.total_timeout_seconds * 1_000:
            raise _invalid()


@dataclass(frozen=True)
class TargetConnectionConfig:
    """Resolved target libpq keywords with all infrastructure values redacted."""

    mode: str
    sslmode: str
    connect_timeout_seconds: int
    _resolved_parameters: tuple[tuple[str, str | int], ...] = field(repr=False)
    _service_file_path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in {"service", "direct"} or self.sslmode != "verify-full":
            raise _invalid()
        _integer(self.connect_timeout_seconds, 1, 60)
        if not isinstance(self._resolved_parameters, tuple):
            raise _invalid()
        try:
            parameters = dict(self._resolved_parameters)
        except (TypeError, ValueError):
            raise _invalid() from None
        if len(parameters) != len(self._resolved_parameters):
            raise _invalid()
        common = (
            "passfile",
            "sslrootcert",
            "sslmode",
            "application_name",
            "connect_timeout",
        )
        if self.mode == "service":
            # The service selector must be first; explicit mandatory controls
            # after it override any weaker profile defaults.
            if tuple(parameters) != ("service", *common):
                raise _invalid()
            if (
                not isinstance(self._service_file_path, str)
                or not Path(self._service_file_path).is_absolute()
                or _SERVICE_NAME.fullmatch(str(parameters["service"])) is None
            ):
                raise _invalid()
        else:
            if set(parameters) != {*common, "host", "port", "dbname", "user"}:
                raise _invalid()
            if self._service_file_path is not None:
                raise _invalid()
            host = str(parameters["host"])
            if (
                host.startswith("/")
                or any(character.isspace() for character in host)
                or any(fragment in host for fragment in ("/", "@", "?", "=", ","))
            ):
                raise _invalid()
            _integer(parameters["port"], 1, 65_535)
        if (
            parameters.get("sslmode") != "verify-full"
            or parameters.get("application_name") != BRERC_TARGET_APPLICATION_NAME
            or parameters.get("connect_timeout") != self.connect_timeout_seconds
        ):
            raise _invalid()
        paths = [parameters.get("passfile"), parameters.get("sslrootcert")]
        if self._service_file_path is not None:
            paths.append(self._service_file_path)
        if any(not isinstance(path, str) or not Path(path).is_absolute() for path in paths):
            raise _invalid()
        if len(paths) != len(set(paths)):
            raise _invalid()
        for key, value in self._resolved_parameters:
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, str | int)
            ):
                raise _invalid()
            if isinstance(value, str):
                _string(value)

    def __repr__(self) -> str:
        return (
            "TargetConnectionConfig("
            f"mode={self.mode!r}, sslmode={self.sslmode!r}, "
            f"connect_timeout_seconds={self.connect_timeout_seconds!r}, "
            "resolved_parameters=<redacted>)"
        )

    def parameters(self) -> dict[str, str | int]:
        """Return a fresh driver mapping; callers must never log it."""
        return dict(self._resolved_parameters)

    def assert_process_environment(self, environ: Mapping[str, str] | None = None) -> None:
        """Recheck ambient password and service-file binding before connection."""
        process = os.environ if environ is None else environ
        if "PGPASSWORD" in process:
            raise _invalid()
        if self.mode == "service" and process.get("PGSERVICEFILE") != self._service_file_path:
            raise _invalid()


@dataclass(frozen=True)
class ReconciliationConfig:
    """Key material for private deterministic source-state reconciliation."""

    secret_env: str
    _secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _environment_name(self.secret_env)
        if (
            not isinstance(self._secret, bytes)
            or len(self._secret) < MIN_RECONCILIATION_SECRET_BYTES
        ):
            raise _invalid()

    def secret_bytes(self) -> bytes:
        """Return a copy for HMAC use by the coordinator; never log this value."""
        return bytes(self._secret)

    def __repr__(self) -> str:
        return f"ReconciliationConfig(secret_env={self.secret_env!r}, secret=<redacted>)"


@dataclass(frozen=True)
class PublicationConfig:
    """Digest-bound policy bytes plus a separate public-record HMAC secret."""

    policy_path: Path = field(repr=False)
    expected_sha256: str = field(repr=False)
    public_id_secret_env: str
    _artifact: bytes = field(repr=False)
    _public_id_secret: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.policy_path, Path)
            or not self.policy_path.is_absolute()
            or self.policy_path.suffix != ".json"
        ):
            raise _invalid()
        expected_digest = _sha256(self.expected_sha256)
        if (
            not isinstance(self._artifact, bytes)
            or not 1 <= len(self._artifact) <= MAX_PUBLICATION_POLICY_BYTES
            or not hmac.compare_digest(
                hashlib.sha256(self._artifact).hexdigest(),
                expected_digest,
            )
        ):
            raise _invalid()
        _environment_name(self.public_id_secret_env)
        if (
            not isinstance(self._public_id_secret, bytes)
            or len(self._public_id_secret) < MIN_RECONCILIATION_SECRET_BYTES
        ):
            raise _invalid()

    def artifact_bytes(self) -> bytes:
        """Return the exact digest-checked JSON bytes for coordinator parsing."""
        return bytes(self._artifact)

    def public_id_secret_bytes(self) -> bytes:
        """Return the separate public-record HMAC key; never log this value."""
        return bytes(self._public_id_secret)

    def __repr__(self) -> str:
        return (
            "PublicationConfig(policy=<redacted>, "
            f"public_id_secret_env={self.public_id_secret_env!r}, "
            "public_id_secret=<redacted>)"
        )


@dataclass(frozen=True)
class SpeciesDictionaryConfig:
    """Exact raw species-dictionary bytes retained for semantic validation."""

    csv_path: Path = field(repr=False)
    expected_raw_sha256: str = field(repr=False)
    _artifact: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.csv_path, Path)
            or not self.csv_path.is_absolute()
            or self.csv_path.suffix != ".csv"
        ):
            raise _invalid()
        expected_digest = _sha256(self.expected_raw_sha256)
        if (
            not isinstance(self._artifact, bytes)
            or not 1 <= len(self._artifact) <= MAX_SPECIES_DICTIONARY_BYTES
            or not hmac.compare_digest(
                hashlib.sha256(self._artifact).hexdigest(),
                expected_digest,
            )
        ):
            raise _invalid()

    def artifact_bytes(self) -> bytes:
        """Return the exact digest-checked CSV bytes for semantic parsing."""
        return bytes(self._artifact)

    def __repr__(self) -> str:
        return "SpeciesDictionaryConfig(artifact=<redacted>)"


@dataclass(frozen=True)
class LoaderConfig:
    """One exact loader deployment configuration."""

    version: str
    source_config_path: Path = field(repr=False)
    publication: PublicationConfig
    species_dictionary: SpeciesDictionaryConfig
    runtime: LoaderRuntimeConfig
    target_connection: TargetConnectionConfig
    reconciliation: ReconciliationConfig

    def __post_init__(self) -> None:
        if self.version != LOADER_CONFIG_VERSION:
            raise _invalid()
        if (
            not isinstance(self.source_config_path, Path)
            or not self.source_config_path.is_absolute()
        ):
            raise _invalid()
        if not isinstance(self.publication, PublicationConfig):
            raise _invalid()
        if not isinstance(self.species_dictionary, SpeciesDictionaryConfig):
            raise _invalid()
        if not isinstance(self.runtime, LoaderRuntimeConfig):
            raise _invalid()
        if not isinstance(self.target_connection, TargetConnectionConfig):
            raise _invalid()
        if not isinstance(self.reconciliation, ReconciliationConfig):
            raise _invalid()
        if self.target_connection.connect_timeout_seconds != self.runtime.connect_timeout_seconds:
            raise _invalid()
        if self.target_connection.mode == "direct":
            parameters = self.target_connection.parameters()
            if (
                parameters["dbname"] != self.runtime.expected_target_database
                or parameters["user"] != self.runtime.expected_target_role
            ):
                raise _invalid()
        protected_paths = {
            Path(str(value))
            for key, value in self.target_connection.parameters().items()
            if key in {"passfile", "sslrootcert"}
        }
        if self.target_connection._service_file_path is not None:
            protected_paths.add(Path(self.target_connection._service_file_path))
        artifact_paths = {
            self.source_config_path,
            self.publication.policy_path,
            self.species_dictionary.csv_path,
        }
        if len(artifact_paths) != 3 or artifact_paths & protected_paths:
            raise _invalid()
        if self.publication.public_id_secret_env == self.reconciliation.secret_env:
            raise _invalid()
        if hmac.compare_digest(
            self.publication.public_id_secret_bytes(),
            self.reconciliation.secret_bytes(),
        ):
            raise _invalid()

    def __repr__(self) -> str:
        return (
            "LoaderConfig("
            f"version={self.version!r}, batch_size={self.runtime.batch_size!r}, "
            f"target_mode={self.target_connection.mode!r}, "
            "source_config_path=<redacted>, target_identity=<redacted>, "
            "publication_policy=<redacted>, species_dictionary=<redacted>, "
            "reconciliation_secret=<redacted>)"
        )


def _parse_runtime(value: object) -> LoaderRuntimeConfig:
    raw = _strict_mapping(value, _RUNTIME_KEYS)
    return LoaderRuntimeConfig(
        expected_target_database=_string(raw["expected_target_database"]),
        expected_target_environment_id=_uuid(raw["expected_target_environment_id"]),
        expected_target_role=_string(raw["expected_target_role"]),
        batch_size=_integer(raw["batch_size"], 100, 100_000),
        initial_min_source_rows=_integer(raw["initial_min_source_rows"], 1, 1_000_000_000),
        initial_max_source_rows=_integer(raw["initial_max_source_rows"], 1, 1_000_000_000),
        refresh_min_source_rows=_integer(raw["refresh_min_source_rows"], 1, 1_000_000_000),
        refresh_max_source_rows=_integer(raw["refresh_max_source_rows"], 1, 1_000_000_000),
        refresh_max_source_row_drop_bps=_integer(raw["refresh_max_source_row_drop_bps"], 0, 10_000),
        refresh_max_source_row_growth_bps=_integer(
            raw["refresh_max_source_row_growth_bps"], 0, 1_000_000_000
        ),
        refresh_max_publication_basis_drop_bps=_integer(
            raw["refresh_max_publication_basis_drop_bps"], 0, 10_000
        ),
        refresh_max_species_drop_bps=_integer(raw["refresh_max_species_drop_bps"], 0, 10_000),
        refresh_max_cell_drop_bps=_integer(raw["refresh_max_cell_drop_bps"], 0, 10_000),
        refresh_max_species_year_drop_bps=_integer(
            raw["refresh_max_species_year_drop_bps"], 0, 10_000
        ),
        connect_timeout_seconds=_integer(raw["connect_timeout_seconds"], 1, 60),
        lock_timeout_ms=_integer(raw["lock_timeout_ms"], 100, 60_000),
        statement_timeout_ms=_integer(raw["statement_timeout_ms"], 1_000, 3_600_000),
        total_timeout_seconds=_integer(raw["total_timeout_seconds"], 60, 86_400),
    )


def _parse_target_connection(
    value: object,
    runtime: LoaderRuntimeConfig,
    environ: Mapping[str, str],
) -> TargetConnectionConfig:
    if "PGPASSWORD" in environ or not isinstance(value, dict):
        raise _invalid()
    mode = value.get("mode")
    keys = (
        _SERVICE_CONNECTION_KEYS
        if mode == "service"
        else _DIRECT_CONNECTION_KEYS
        if mode == "direct"
        else None
    )
    if keys is None:
        raise _invalid()
    raw = _strict_mapping(value, keys)
    if raw["sslmode"] != "verify-full":
        raise _invalid()

    passfile_env = _environment_name(raw["passfile_env"])
    rootcert_env = _environment_name(raw["sslrootcert_env"])
    common: dict[str, str | int] = {
        "passfile": _resolved_path(passfile_env, environ),
        "sslrootcert": _resolved_path(rootcert_env, environ),
        "sslmode": "verify-full",
        "application_name": BRERC_TARGET_APPLICATION_NAME,
        "connect_timeout": runtime.connect_timeout_seconds,
    }
    if common["passfile"] == common["sslrootcert"]:
        raise _invalid()

    service_file: str | None = None
    if mode == "service":
        service_env = _environment_name(raw["service_env"])
        service_file_env = _environment_name(raw["service_file_env"])
        if service_file_env != "PGSERVICEFILE":
            raise _invalid()
        service = _resolved(service_env, environ)
        if _SERVICE_NAME.fullmatch(service) is None:
            raise _invalid()
        service_file = _resolved_path(service_file_env, environ)
        if service_file in {common["passfile"], common["sslrootcert"]}:
            raise _invalid()
        parameters: dict[str, str | int] = {"service": service, **common}
    else:
        names = {
            key: _environment_name(raw[f"{key}_env"])
            for key in ("host", "port", "database", "user")
        }
        host = _resolved(names["host"], environ)
        if (
            host.startswith("/")
            or any(character.isspace() for character in host)
            or any(fragment in host for fragment in ("/", "@", "?", "=", ","))
        ):
            raise _invalid()
        port_text = _resolved(names["port"], environ)
        if not port_text.isascii() or not port_text.isdecimal():
            raise _invalid()
        port = _integer(int(port_text), 1, 65_535)
        database = _resolved(names["database"], environ)
        user = _resolved(names["user"], environ)
        if database != runtime.expected_target_database or user != runtime.expected_target_role:
            raise _invalid()
        parameters = {
            **common,
            "host": host,
            "port": port,
            "dbname": database,
            "user": user,
        }
    return TargetConnectionConfig(
        mode=mode,
        sslmode="verify-full",
        connect_timeout_seconds=runtime.connect_timeout_seconds,
        _resolved_parameters=tuple(parameters.items()),
        _service_file_path=service_file,
    )


def _parse_reconciliation(
    value: object,
    environ: Mapping[str, str],
) -> ReconciliationConfig:
    raw = _strict_mapping(value, _RECONCILIATION_KEYS)
    secret_env = _environment_name(raw["secret_env"])
    secret = _resolved(secret_env, environ).encode("utf-8")
    if len(secret) < MIN_RECONCILIATION_SECRET_BYTES:
        raise _invalid()
    return ReconciliationConfig(secret_env=secret_env, _secret=secret)


def _parse_publication(
    value: object,
    environ: Mapping[str, str],
) -> PublicationConfig:
    raw = _strict_mapping(value, _PUBLICATION_KEYS)
    policy_path = Path(_string(raw["policy_path"]))
    expected_sha256 = _sha256(raw["expected_sha256"])
    artifact = _publication_policy_artifact(policy_path, expected_sha256)
    public_id_secret_env = _environment_name(raw["public_id_secret_env"])
    public_id_secret = _resolved(public_id_secret_env, environ).encode("utf-8")
    if len(public_id_secret) < MIN_RECONCILIATION_SECRET_BYTES:
        raise _invalid()
    return PublicationConfig(
        policy_path=policy_path,
        expected_sha256=expected_sha256,
        public_id_secret_env=public_id_secret_env,
        _artifact=artifact,
        _public_id_secret=public_id_secret,
    )


def _parse_species_dictionary(value: object) -> SpeciesDictionaryConfig:
    raw = _strict_mapping(value, _SPECIES_DICTIONARY_KEYS)
    csv_path = Path(_string(raw["csv_path"]))
    expected_raw_sha256 = _sha256(raw["expected_raw_sha256"])
    artifact = _species_dictionary_artifact(csv_path, expected_raw_sha256)
    return SpeciesDictionaryConfig(
        csv_path=csv_path,
        expected_raw_sha256=expected_raw_sha256,
        _artifact=artifact,
    )


def load_loader_config(
    path: str | Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> LoaderConfig:
    """Load one bounded credential-free loader configuration.

    The referenced source configuration is deliberately not parsed here; the
    coordinator passes it to the existing trusted source loader. Incremental CLI
    blocking therefore occurs before either source or target connection setup.
    """
    if not isinstance(path, str | Path):
        raise _invalid()
    config_path = Path(path)
    try:
        size = config_path.stat().st_size
    except OSError:
        raise _invalid() from None
    if not 1 <= size <= MAX_CONFIG_BYTES:
        raise _invalid()
    try:
        raw = config_path.read_bytes()
    except OSError:
        raise _invalid() from None
    if not 1 <= len(raw) <= MAX_CONFIG_BYTES:
        raise _invalid()
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise _invalid() from None
    document = _strict_mapping(_restricted_yaml(text), _ROOT_KEYS)
    if document["loader_config_version"] != LOADER_CONFIG_VERSION:
        raise _invalid()
    source_path = Path(_string(document["source_config_path"]))
    if not source_path.is_absolute():
        raise _invalid()
    resolved_environ = os.environ if environ is None else environ
    runtime = _parse_runtime(document["runtime"])
    target = _parse_target_connection(document["target_connection"], runtime, resolved_environ)
    reconciliation = _parse_reconciliation(document["reconciliation"], resolved_environ)
    publication = _parse_publication(document["publication"], resolved_environ)
    species_dictionary = _parse_species_dictionary(document["species_dictionary"])
    return LoaderConfig(
        version=LOADER_CONFIG_VERSION,
        source_config_path=source_path,
        publication=publication,
        species_dictionary=species_dictionary,
        runtime=runtime,
        target_connection=target,
        reconciliation=reconciliation,
    )
