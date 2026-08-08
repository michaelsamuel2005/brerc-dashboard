# etl/provenance.py
"""
Writes the single-row `provenance` table, which feeds the
"About this data" section of the public dashboard (public_provenance
view, per the B6 schema notes).

provenance is DIFFERENT from the other tables this pipeline writes:
species / occurrence_public / distribution_cell are all derived from
the actual occurrence data each run. provenance is mostly static,
human-written text about the project as a whole (where the data comes
from, its known limitations, how privacy is handled) - the kind of
thing someone writes once and rarely changes, not something computed
from a dataframe.

>>> THE TEXT BELOW IS A PLACEHOLDER <<<
sources / caveats / sensitivity_policy_summary need real content from
whoever owns the public-facing copy for the dashboard - don't ship the
values below to production as-is.
"""

from datetime import date, datetime, timezone

# TODO: replace with the real, agreed wording before this goes live.
DEFAULT_SOURCES = [
    "BRERC (Bristol Regional Environmental Records Centre)",
]

DEFAULT_CAVEATS = [
    "Coverage varies by area and recorder effort - absence of records "
    "does not mean absence of a species.",
    "Some historic records may lack precise dates.",
]

DEFAULT_SENSITIVITY_POLICY_SUMMARY = (
    "Locations for sensitive species are shown at reduced precision, "
    "and any species x cell x year combination with very few records "
    "is hidden entirely, so that individual sensitive records can't "
    "be pinpointed from public data."
)


def upsert_provenance(
    connection,
    load_mode: str,
    sources=None,
    caveats=None,
    sensitivity_policy_summary=None,
    last_updated: date = None,
):
    """
    Writes/refreshes the single provenance row (id is always 1).
    Call once per pipeline run so last_updated reflects the most
    recent successful load.
    """
    sources = sources or DEFAULT_SOURCES
    caveats = caveats or DEFAULT_CAVEATS
    sensitivity_policy_summary = (
        sensitivity_policy_summary or DEFAULT_SENSITIVITY_POLICY_SUMMARY
    )
    last_updated = last_updated or datetime.now(timezone.utc).date()
    load_date = datetime.now(timezone.utc)

    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO provenance
                (id, sources, caveats, last_updated,
                 sensitivity_policy_summary, "Load", "Load_date")
            VALUES
                (1, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                sources                     = EXCLUDED.sources,
                caveats                     = EXCLUDED.caveats,
                last_updated                = EXCLUDED.last_updated,
                sensitivity_policy_summary  = EXCLUDED.sensitivity_policy_summary,
                "Load"                      = EXCLUDED."Load",
                "Load_date"                 = EXCLUDED."Load_date"
            """,
            (
                sources,
                caveats,
                last_updated,
                sensitivity_policy_summary,
                load_mode,
                load_date,
            ),
        )

    connection.commit()