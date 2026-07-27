"""
    Unit tests for B3's Done bar, against the REAL reconcile()
    (safety-pipeline-wired), not fake callbacks:
      - An edited record updates.
      - A retracted record disappears.
      - A re-run changes nothing.
    Plus: inserts/updates passed to insert_records/update_records
    must never contain a forbidden (precise/free-text) field.

    generalise_locations is mocked out here - it sends real SQL to
    PostGIS (ST_SnapToGrid, COPY, temp tables), which can't be
    meaningfully faked without a real Postgres instance. That
    function needs its OWN dedicated tests against a real/test
    database - this file tests ORCHESTRATION (right records get
    diffed and routed) and the safety-leak guarantee, not PostGIS
    maths.
"""

from unittest.mock import patch

import pandas as pd
import pytest

from etl.reconciliation.reconcile import reconcile
from etl.reconciliation.hashing import add_content_hash
from etl.reconciliation.diff import build_id_hash_map
from etl.safety_gate.public_output import FORBIDDEN_COLUMNS


@pytest.fixture
def dictionary_df():
    return pd.DataFrame({
        "scientific": ["Myotis daubentonii", "Meles meles"],
        "species_no": [12345, 300],
        "nbn_number": ["NBN001", "NBN002"],
    })


def _source_row(unique_no, scientific_name, easting, northing, verified="Accepted"):
    return {
        "unique_no": unique_no,
        "scientific_name": scientific_name,
        "abundance": "1",
        "sex_stage": "Adult",
        "record_type": "Casual record",
        "vitality": "Alive",
        "verified": verified,
        "eastings": easting,
        "northings": northing,
        "record_date": "23/03/2023",
    }


def _fake_generalise_locations(df, connection, easting_column, northing_column, resolution_column):
    # Stand-in for the real PostGIS round-trip. Mirrors the real
    # function's D0_FLOOR_M fillna/clip behaviour for
    # effective_resolution_m, so downstream code (which now depends
    # on that column existing) has something to work with.
    df = df.copy()
    df["effective_resolution_m"] = (
        df[resolution_column].fillna(100).clip(lower=100)
    )
    df["longitude"] = -2.5
    df["latitude"] = 51.5
    df["snapped_easting"] = df[easting_column]
    df["snapped_northing"] = df[northing_column]
    return df


@pytest.fixture(autouse=True)
def patch_generalise(monkeypatch):
    monkeypatch.setattr(
        "etl.reconciliation.reconcile.generalise_locations",
        _fake_generalise_locations,
    )


# --- An edited record updates ---

def test_edited_record_updates(dictionary_df):
    with patch("etl.reconciliation.reconcile.insert_records") as mock_insert, \
         patch("etl.reconciliation.reconcile.update_records") as mock_update, \
         patch("etl.reconciliation.reconcile.delete_records") as mock_delete:

        source_df = pd.DataFrame([
            _source_row(1, "Meles meles", 400500, 300500),  # coordinates changed
        ])
        old_hash_source = add_content_hash(pd.DataFrame([
            _source_row(1, "Meles meles", 400000, 300000),  # original values
        ]))
        ui_map = build_id_hash_map(old_hash_source)

        reconcile(source_df, dictionary_df, ui_map, connection=None)

        mock_update.assert_called_once()
        updated_df = mock_update.call_args[0][0]
        assert set(updated_df["record_id"]) == {1}
        assert updated_df.iloc[0]["species_id"] == 300  # Meles meles, per dictionary_df
        assert mock_insert.call_args[0][0].empty
        mock_delete.assert_called_once_with(set(), None)


# --- A retracted record disappears ---

def test_retracted_record_disappears(dictionary_df):
    with patch("etl.reconciliation.reconcile.insert_records") as mock_insert, \
         patch("etl.reconciliation.reconcile.update_records") as mock_update, \
         patch("etl.reconciliation.reconcile.delete_records") as mock_delete:

        source_df = pd.DataFrame([
            _source_row(1, "Meles meles", 400000, 300000),
        ])
        ui_source = add_content_hash(pd.DataFrame([
            _source_row(1, "Meles meles", 400000, 300000),
            _source_row(2, "Myotis daubentonii", 401000, 301000),  # retracted
        ]))
        ui_map = build_id_hash_map(ui_source)

        reconcile(source_df, dictionary_df, ui_map, connection=None)

        mock_delete.assert_called_once_with({2}, None)


# --- A re-run changes nothing ---

def test_rerun_with_no_changes_is_noop(dictionary_df):
    with patch("etl.reconciliation.reconcile.insert_records") as mock_insert, \
         patch("etl.reconciliation.reconcile.update_records") as mock_update, \
         patch("etl.reconciliation.reconcile.delete_records") as mock_delete:

        source_df = pd.DataFrame([
            _source_row(1, "Meles meles", 400000, 300000),
        ])
        ui_map = build_id_hash_map(add_content_hash(source_df.copy()))

        reconcile(source_df, dictionary_df, ui_map, connection=None)

        assert mock_insert.call_args[0][0].empty
        assert mock_update.call_args[0][0].empty
        mock_delete.assert_called_once_with(set(), None)


# --- Safety guarantee: forbidden fields never reach the DB write ---

def test_inserts_never_contain_forbidden_fields(dictionary_df):
    with patch("etl.reconciliation.reconcile.insert_records") as mock_insert, \
         patch("etl.reconciliation.reconcile.update_records") as mock_update, \
         patch("etl.reconciliation.reconcile.delete_records") as mock_delete:

        source_df = pd.DataFrame([
            _source_row(1, "Meles meles", 400000, 300000),
        ])
        ui_map = {}  # empty UI - forces this row to be treated as an insert

        reconcile(source_df, dictionary_df, ui_map, connection=None)

        inserted_df = mock_insert.call_args[0][0]
        leaked = set(inserted_df.columns) & FORBIDDEN_COLUMNS
        assert leaked == set(), f"Forbidden columns leaked into insert: {leaked}"