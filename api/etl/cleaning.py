"""Exploratory helpers. NOT part of the safety boundary.

The original `clean_data()` printed a dataframe summary and returned the frame
unchanged - useful for looking at a new extract, but it performed no cleaning, so
nothing downstream should depend on it. It is kept here, renamed to say what it
actually does, so the intent is not mistaken again.

Real cleaning, generalisation and aggregation live in:

    gridref.py      parse and coarsen OS grid references
    sensitivity.py  the sensitive-species gate (generalise, never drop)
    contract.py     the public allow-list and verified-status parity
    aggregate.py    map cells and the year series
    pipeline.py     the whole boundary, with an explicit column mapping

`clean_data` is retained as a deprecated alias so existing notebooks keep working,
but it must not be used in the pipeline.
"""

from __future__ import annotations

import warnings
from typing import Any


def describe_dataset(df: Any) -> dict[str, Any]:
    """Return a STRUCTURAL summary of a dataframe. Never prints record content.

    The original version printed `df.head()`, which puts real grid references,
    place names, recorder attributions and comments into stdout - and therefore
    into CI logs, terminal scrollback and any log aggregator. A diagnostic helper
    must not be the thing that leaks the data the pipeline exists to protect.

    Returns counts and column metadata only. Callers decide what to display.
    """
    return {
        "rows": len(df),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
        "non_null": {str(c): int(df[c].notna().sum()) for c in df.columns},
        "distinct": {str(c): int(df[c].nunique()) for c in df.columns},
    }


def clean_data(df: Any) -> Any:
    """Deprecated alias for `describe_dataset`.

    The name implied cleaning that never happened. Kept so older code does not
    break, but it warns, and it must not appear in the pipeline.
    """
    warnings.warn(
        "clean_data() never cleaned anything - it printed a summary and returned the "
        "frame unchanged, putting real records into stdout. Use describe_dataset() "
        "for a structural summary, or pipeline.run_pipeline() for the real boundary.",
        DeprecationWarning,
        stacklevel=2,
    )
    return describe_dataset(df)
