"""Trusted, read-only adapters for BRERC's private source database.

This package is deliberately separate from :mod:`etl`.  Database and YAML
dependencies belong at the edge of the system; the publication safety boundary
remains importable and testable with the Python standard library alone.
"""

from .config import (
    BRERC_SOURCE_APPLICATION_NAME,
    ConnectionConfig,
    RuntimeConfig,
    SourceConfigError,
    SourceConnectorConfig,
    SourceLocation,
    load_source_config,
)
from .errors import (
    SourceCancelled,
    SourceCleanupFailed,
    SourceConfigurationError,
    SourceConnectionFailed,
    SourceDatabaseFailed,
    SourceDriverUnavailable,
    SourceProtocolError,
    SourceTimedOut,
    TrustedSourceConnectorError,
)
from .models import SourcePreflightReport
from .postgres import TrustedPostgreSQLSourceConnector

__all__ = [
    "BRERC_SOURCE_APPLICATION_NAME",
    "ConnectionConfig",
    "RuntimeConfig",
    "SourceCancelled",
    "SourceCleanupFailed",
    "SourceConfigError",
    "SourceConfigurationError",
    "SourceConnectionFailed",
    "SourceConnectorConfig",
    "SourceDatabaseFailed",
    "SourceDriverUnavailable",
    "SourceLocation",
    "SourcePreflightReport",
    "SourceProtocolError",
    "SourceTimedOut",
    "TrustedPostgreSQLSourceConnector",
    "TrustedSourceConnectorError",
    "load_source_config",
]
