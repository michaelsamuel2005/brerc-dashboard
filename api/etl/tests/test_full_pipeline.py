"""
Full ETL integration test.

Checks:
- records flow through reconciliation
- species resolution works
- verified filtering works
- safety pipeline runs before DB writes
- forbidden fields never reach public DB
- species index is generated
- no unexpected updates/deletes happen

python -m pytest etl/tests/test_full_pipeline.py -v
"""

from unittest.mock import patch

import pandas as pd
import pytest

from etl.reconciliation.reconcile import reconcile
from etl.safety_gate.public_output import FORBIDDEN_COLUMNS


# --------------------------------------------------
# Fixtures
# --------------------------------------------------

@pytest.fixture
def dictionary_df():
    return pd.DataFrame({
        "scientific": [
            "Meles meles",
            "Myotis daubentonii",
        ],
        "species_no": [
            300,
            12345,
        ],
        "nbn_number": [
            "NBN002",
            "NBN001",
        ],
        "common_name": [
            "European badger",
            "Daubenton's bat",
        ],
        "taxanb": [
            "NBN002",
            "NBN001",
        ],
    })


@pytest.fixture
def source_df():
    return pd.DataFrame([

        # Should survive full pipeline
        {
            "unique_no": 1,
            "scientific_name": "Meles meles",
            "abundance": "1",
            "sex_stage": "Adult",
            "record_type": "Casual record",
            "vitality": "Alive",
            "verified": "Accepted",
            "eastings": 400000,
            "northings": 300000,
            "record_date": "23/03/2023",
        },

        # Should be removed by verified filter
        {
            "unique_no": 2,
            "scientific_name": "Myotis daubentonii",
            "abundance": "1",
            "sex_stage": "Adult",
            "record_type": "Casual record",
            "vitality": "Alive",
            "verified": "Rejected",
            "eastings": 401000,
            "northings": 301000,
            "record_date": "23/03/2023",
        },
    ])


# --------------------------------------------------
# Fake generalisation
# Avoids requiring PostGIS during this test
# --------------------------------------------------

def fake_generalise_locations(
    df,
    connection,
    easting_column,
    northing_column,
    resolution_column,
):

    df = df.copy()

    df["effective_resolution_m"] = 100

    df["longitude"] = -2.5
    df["latitude"] = 51.5

    df["snapped_easting"] = df[easting_column]
    df["snapped_northing"] = df[northing_column]

    return df


# --------------------------------------------------
# Full ETL integration test
# --------------------------------------------------

def test_full_etl_pipeline(
    source_df,
    dictionary_df,
):

    with patch(
        "etl.reconciliation.reconcile.generalise_locations",
        fake_generalise_locations,
    ), \
    patch(
        "etl.reconciliation.reconcile.upsert_species"
    ) as mock_species, \
    patch(
        "etl.reconciliation.reconcile.insert_records"
    ) as mock_insert, \
    patch(
        "etl.reconciliation.reconcile.update_records"
    ) as mock_update, \
    patch(
        "etl.reconciliation.reconcile.delete_records"
    ) as mock_delete:


        changes = reconcile(
            source_df,
            dictionary_df,
            ui_map={},
            connection=None,
        )


        # ---------------------------------
        # Reconciliation layer
        # ---------------------------------

        assert changes["inserts"] == {1, 2}
        assert changes["updates"] == set()
        assert changes["deletes"] == set()


        # ---------------------------------
        # Database insert receives output
        # from safety pipeline only
        # ---------------------------------

        inserted_df = mock_insert.call_args[0][0]


        assert not inserted_df.empty


        # ---------------------------------
        # Forbidden fields never leak
        # ---------------------------------

        leaked_columns = (
            set(inserted_df.columns)
            &
            FORBIDDEN_COLUMNS
        )

        assert leaked_columns == set(), (
            f"Forbidden columns leaked: {leaked_columns}"
        )


        # ---------------------------------
        # D5 verified filtering
        # rejected record removed
        # ---------------------------------

        assert set(inserted_df["record_id"]) == {1}


        # ---------------------------------
        # Species resolution
        # ---------------------------------

        assert (
            inserted_df.iloc[0]["species_id"]
            == 300
        )


        # ---------------------------------
        # Species table updated
        # ---------------------------------

        mock_species.assert_called_once()


        # ---------------------------------
        # No updates/deletes needed
        # ---------------------------------

        assert (
            mock_update.call_args[0][0]
            .empty
        )

        mock_delete.assert_called_once_with(
            set(),
            None,
        )