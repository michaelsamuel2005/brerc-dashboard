"""Image-licence normalisation + the fail-closed reuse decision.  TODO (build this).

Learning Guide -> 04-the-api.md (section 5).
Answer Key: brerc-public-dashboard/api/app/services/licensing.py
"""
from __future__ import annotations

UNKNOWN = "unknown"


def normalise_licence(raw: str | None) -> str:
    """TODO: map any licence string to a canonical token (UNKNOWN if unrecognised)."""
    raise NotImplementedError("TODO: implement normalise_licence (Module 4)")


def is_reusable(token: str, allowed: set[str]) -> bool:
    """TODO: True only if the token is recognised AND in the allow-list."""
    raise NotImplementedError("TODO: implement is_reusable (Module 4)")
