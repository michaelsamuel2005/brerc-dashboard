"""
    Unit tests for B4's Done bar:
      - Totals reconcile.
      - Only accepted (+ marked legacy) records appear.
      - A count of one can't pinpoint a sensitive record.
"""

import pandas as pd

from etl.aggregation.filtering import (
    filter_accepted_records,
    ACCEPTED_VERIFIED_VALUES,
)
from etl.aggregation.species_index import build_species_index
from etl.aggregation.counts import aggregate_counts, suppress_low_counts

# Pull the real accepted-value string straight from your code, rather
# than retyping it - this stays correct even while the ñ/encoding
# question is still unresolved with BRERC.
ACCEPTED_VALUE = next(iter(ACCEPTED_VERIFIED_VALUES))


def _make_records():
    return pd.DataFrame([
        {"unique_no": 1, "species_no": 100, "scientific_name": "Myotis daubentonii",
         "verified": ACCEPTED_VALUE,
         "easting": 400000, "northing": 300000, "record_date": "23/03/2023"},
        {"unique_no": 2, "species_no": 100, "scientific_name": "Myotis daubentonii",
         "verified": ACCEPTED_VALUE,
         "easting": 400100, "northing": 300100, "record_date": "24/03/2023"},
        {"unique_no": 3, "species_no": 200, "scientific_name": "Pipistrellus pipistrellus",
         "verified": "Rejected",
         "easting": 401000, "northing": 301000, "record_date": "01/06/2023"},
        {"unique_no": 4, "species_no": 300, "scientific_name": "Meles meles",
         "verified": "BRERC",
         "easting": 402000, "northing": 302000, "record_date": "10/07/2023"},
    ])


# --- Only accepted (+ marked legacy) records appear ---

def test_filter_keeps_accepted_and_legacy_only():
    records = _make_records()
    filtered = filter_accepted_records(records, verified_column="verified")

    assert set(filtered["unique_no"]) == {1, 2, 4}
    assert 3 not in set(filtered["unique_no"])


def test_species_index_built_from_loaded_records_only():
    records = _make_records()
    filtered = filter_accepted_records(records, verified_column="verified")
    index = build_species_index(filtered)

    assert set(index["species_no"]) == {100, 300}


# --- Totals reconcile ---

def test_totals_reconcile_with_filtered_record_count():
    records = _make_records()
    filtered = filter_accepted_records(records, verified_column="verified")
    aggregated = aggregate_counts(
        filtered,
        easting_column="easting",
        northing_column="northing",
        date_column="record_date",
        cell_size_m=10_000,
    )

    assert aggregated["count"].sum() == len(filtered)


# --- A count of one can't pinpoint a sensitive record ---

def test_low_count_cell_is_suppressed():
    aggregated = pd.DataFrame([
        {"species_no": 100, "grid_cell": "TQ 2 7", "year": 2023, "count": 1},
        {"species_no": 200, "grid_cell": "TQ 3 8", "year": 2023, "count": 12},
    ])
    result = suppress_low_counts(aggregated, threshold=5)

    low_count_row = result[result["species_no"] == 100].iloc[0]
    high_count_row = result[result["species_no"] == 200].iloc[0]

    assert low_count_row["suppressed"] == True
    assert pd.isna(low_count_row["count"])  # the raw "1" never appears
    assert high_count_row["suppressed"] == False
    assert high_count_row["count"] == 12


def test_suppression_boundary_at_threshold_is_not_suppressed():
    # As currently coded, suppression is strictly "count < threshold",
    # so a count exactly AT the threshold is shown, not suppressed.
    # TODO: confirm with BRERC whether "below threshold" should be
    # exclusive (current behaviour) or inclusive (<=) - this is a
    # real policy decision, not something to assume either way.
    aggregated = pd.DataFrame([
        {"species_no": 100, "grid_cell": "TQ 2 7", "year": 2023, "count": 5},
    ])
    result = suppress_low_counts(aggregated, threshold=5)

    assert result.iloc[0]["suppressed"] == False
    assert result.iloc[0]["count"] == 5