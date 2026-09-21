"""Fixed, non-sensitive failures for the BRERC release loader boundary."""

from __future__ import annotations


class LoaderError(RuntimeError):
    """Base failure whose string is safe for an ordinary operator log."""

    code = "LOADER_FAILED"
    safe_message = "the BRERC release loader failed"

    def __init__(self) -> None:
        super().__init__(f"{self.code}: {self.safe_message}")


class LoaderConfigurationError(LoaderError):
    """The credential-free loader configuration is missing or unsafe."""

    code = "LOADER_CONFIGURATION_INVALID"
    safe_message = "the release loader configuration is invalid"


class IncrementalSourceContractBlocked(LoaderError):
    """The current BRERC source contract cannot support incremental loading."""

    code = "INCREMENTAL_SOURCE_CONTRACT_BLOCKED"
    safe_message = "incremental loading is blocked by the current source contract"


class LoaderCoordinatorUnavailable(LoaderError):
    """The separately packaged PostgreSQL coordinator cannot be imported."""

    code = "LOADER_COORDINATOR_UNAVAILABLE"
    safe_message = "the PostgreSQL release coordinator is unavailable"


class LoaderExecutionFailed(LoaderError):
    """A coordinator operation failed without exposing adapter diagnostics."""

    code = "LOADER_EXECUTION_FAILED"
    safe_message = "the release loader operation failed"


class LoaderPolicyInvalid(LoaderError):
    """The retained publication-policy artifact is invalid or not approved."""

    code = "LOADER_POLICY_INVALID"
    safe_message = "the publication policy artifact is invalid or not approved"


class LoaderReleaseBlocked(LoaderError):
    """External release evidence required by the source or policy is absent."""

    code = "LOADER_RELEASE_BLOCKED"
    safe_message = "the release is blocked by unapproved external evidence"


class LoaderConnectionFailed(LoaderError):
    code = "LOADER_TARGET_CONNECTION_FAILED"
    safe_message = "the publication database connection failed"


class LoaderTargetProtocolError(LoaderError):
    code = "LOADER_TARGET_PROTOCOL_INVALID"
    safe_message = "the publication database does not match the reviewed protocol"


class LoaderAlreadyRunning(LoaderError):
    code = "LOADER_ALREADY_RUNNING"
    safe_message = "another loader currently owns the source activation lock"


class LoaderCandidateInvalid(LoaderError):
    code = "LOADER_CANDIDATE_INVALID"
    safe_message = "the candidate release failed automatic reconciliation"


class LoaderSourceCountRejected(LoaderError):
    code = "LOADER_SOURCE_COUNT_REJECTED"
    safe_message = "the source count is outside the approved automatic bounds"


class LoaderCleanupFailed(LoaderError):
    code = "LOADER_CLEANUP_FAILED"
    safe_message = "the loader could not close its database resources safely"


class LoaderCleanupPending(LoaderError):
    """A previous terminal candidate still has durable payload to purge."""

    code = "LOADER_CLEANUP_PENDING"
    safe_message = "a previous inactive candidate still requires automatic cleanup"
