"""PUBLICATION CORE shim, SUPERSEDED by sensitivity.py; NOT on the live nightly path.

Calling the old function now fails loudly. The import itself still succeeds, so
scripts/guard_stdlib_only.py can keep this file inside its boundary set.

The filter that runs today is etl/aggregation/cell_filtering.py (pandas, via
etl.job -> etl.nightly_pipeline through etl.reconciliation.reconcile and
etl.aggregation.counts). It selects by verification status, which the
publication core carries in etl/contract.py (`normalise_verified`) against
`PublicationPolicy.accepted_verification_values`, applied in etl/pipeline.py.
This shim replaces nothing on that path.

WHAT THIS MODULE USED TO DO, AND WHY IT WAS REPLACED
----------------------------------------------------
    return df[~df["species_id"].isin(SENSITIVE_SPECIES_IDS)].copy()

It REMOVED sensitive species from the public dataset. That is safe from a
disclosure standpoint, which is why it survived review - but it contradicts
`Data_Governance_and_Compliance.md`:

    "Generalise, do not randomise - present as presence-in-a-coarser-square"
    "Supported public resolutions mirror NBN: 1 km, 2 km, 10 km, 50 km, 100 km"

Dropping is not generalising. A public distribution map that silently omits
protected species shows a false picture with no indication anything is missing,
and removes exactly the records BRERC most often needs to publish at a coarse
resolution.

It also hard-coded the column name `species_id`, which the supplied data does not
use. That raises a KeyError - fail-closed and therefore survivable - but the
obvious quick fix (a `.get()` or a try/except) would turn it fail-OPEN, with
nothing gated at all. `pipeline.ColumnMap` now requires the mapping explicitly.

Use `sensitivity.generalise()` instead. This shim exists so that any code still
importing the old function fails immediately rather than quietly reverting to
drop semantics.
"""

from __future__ import annotations

from .sensitivity import SENSITIVE_SPECIES_IDS  # re-exported: the ids are unchanged

__all__ = ["SENSITIVE_SPECIES_IDS", "filter_sensitive_species"]


def filter_sensitive_species(df):
    raise NotImplementedError(
        "filter_sensitive_species() removed sensitive species instead of generalising "
        "them, which contradicts Data_Governance_and_Compliance.md. Use "
        "sensitivity.generalise(grid_ref, species_id), or pipeline.run_pipeline() for "
        "a whole dataset. See api/etl/README.md."
    )
