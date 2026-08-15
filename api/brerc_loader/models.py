"""Validated, log-safe value objects shared with the future DB coordinator."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class LoadMode(str, Enum):
    """Explicit operator commands; never represented by a persistent boolean."""

    INITIAL = "initial"
    INCREMENTAL = "incremental"


class RunState(str, Enum):
    """Terminal state the coordinator may return to the public CLI."""

    SUCCEEDED = "succeeded"


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError):
        raise ValueError(f"{label} must be a canonical UUID") from None
    canonical = str(parsed)
    if value != canonical:
        raise ValueError(f"{label} must be a canonical UUID")
    return canonical


@dataclass(frozen=True)
class LoaderRunReport:
    """Small safe success envelope returned by ``brerc_loader.postgres``.

    The PostgreSQL coordinator must return this exact type from
    ``run_load(config, mode)``. It deliberately carries only opaque identifiers,
    structural counts and a release digest: never rows, grid references, source
    identifiers, SQL, connection values or exception text.
    """

    run_id: str
    release_id: str
    mode: LoadMode
    state: RunState
    source_rows: int
    public_records: int
    distribution_cells: int
    candidate_sha256: str
    activated: bool

    def __post_init__(self) -> None:
        _canonical_uuid(self.run_id, "run_id")
        _canonical_uuid(self.release_id, "release_id")
        if not isinstance(self.mode, LoadMode):
            raise ValueError("mode must be a LoadMode")
        if self.state is not RunState.SUCCEEDED:
            raise ValueError("a CLI success report must be in the succeeded state")
        for label, value in (
            ("source_rows", self.source_rows),
            ("public_records", self.public_records),
            ("distribution_cells", self.distribution_cells),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if (
            not isinstance(self.candidate_sha256, str)
            or _DIGEST.fullmatch(self.candidate_sha256) is None
        ):
            raise ValueError("candidate_sha256 must be a lowercase SHA-256 digest")
        if self.activated is not True:
            raise ValueError("a CLI success report must describe an activated release")
