"""Sanitised failures raised by the trusted BRERC source connector.

Database adapters often include the SQL statement, connection string, or bound
values in their exception text.  None of that is safe to copy into job logs, so
the connector translates adapter failures into these fixed, content-free
messages and suppresses the original exception when it crosses the boundary.
"""

from __future__ import annotations


class TrustedSourceConnectorError(RuntimeError):
    """Base class for connector failures that are safe to display in logs."""

    code = "SOURCE_CONNECTOR_FAILED"
    safe_message = "trusted PostgreSQL source extraction failed"

    def __init__(self) -> None:
        super().__init__(f"{self.code}: {self.safe_message}")


class SourceConfigurationError(TrustedSourceConnectorError):
    """Resolved connection settings are incomplete or unsafe."""

    code = "SOURCE_CONFIGURATION_INVALID"
    safe_message = "trusted PostgreSQL source configuration is invalid"


class SourceDriverUnavailable(TrustedSourceConnectorError):
    """The explicitly supported PostgreSQL driver is unavailable."""

    code = "SOURCE_DRIVER_UNAVAILABLE"
    safe_message = "the PostgreSQL source driver is not installed"


class SourceConnectionFailed(TrustedSourceConnectorError):
    """A connection could not be opened without exposing adapter diagnostics."""

    code = "SOURCE_CONNECTION_FAILED"
    safe_message = "the trusted PostgreSQL source connection could not be opened"


class SourceDatabaseFailed(TrustedSourceConnectorError):
    """A database operation failed; raw driver text is deliberately withheld."""

    code = "SOURCE_DATABASE_FAILED"
    safe_message = "the trusted PostgreSQL source operation failed"


class SourceProtocolError(TrustedSourceConnectorError):
    """The database did not return the exact fixed result shape expected."""

    code = "SOURCE_PROTOCOL_MISMATCH"
    safe_message = "the PostgreSQL source returned an unexpected result shape"


class SourceCancelled(TrustedSourceConnectorError):
    """The caller cancelled the extraction; no partial result is usable."""

    code = "SOURCE_EXTRACTION_CANCELLED"
    safe_message = "the trusted PostgreSQL source extraction was cancelled"


class SourceTimedOut(TrustedSourceConnectorError):
    """The total connector deadline elapsed; partial work is discarded."""

    code = "SOURCE_EXTRACTION_TIMED_OUT"
    safe_message = "the trusted PostgreSQL source extraction exceeded its deadline"


class SourceCleanupFailed(TrustedSourceConnectorError):
    """Rollback or connection cleanup failed, invalidating an apparent success."""

    code = "SOURCE_CLEANUP_FAILED"
    safe_message = "the PostgreSQL source connection could not be closed safely"
