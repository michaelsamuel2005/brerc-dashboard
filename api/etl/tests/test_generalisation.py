import pandas as pd

from etl.safety_gate.generalisation import (
    generalise_locations,
)


def test_generalise_locations_resolution_tiers(connection):
    df = pd.DataFrame(
        {
            "easting": [
                359234,
                359234,
                359234,
                359234,
                359234,
            ],
            "northing": [
                173456,
                173456,
                173456,
                173456,
                173456,
            ],
            "resolution": [
                None,    # should default to 10 km
                50,      # should be raised to 100 m
                1000,    # should remain 1 km
                2000,    # should remain 2 km
                10000,   # should remain 10 km
            ],
        }
    )

    result = generalise_locations(
        df=df,
        connection=connection,
        easting_column="easting",
        northing_column="northing",
        resolution_column="resolution",
    )

    assert result["effective_resolution_m"].tolist() == [
        10000,
        100,
        1000,
        2000,
        10000,
    ]

    assert result["longitude"].notna().all()
    assert result["latitude"].notna().all()