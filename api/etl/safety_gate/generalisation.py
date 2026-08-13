"""
Snaps British National Grid (BNG EPSG:27700) coordinates to a resolution grid 
using PostGIS, transforms them to WGS84 (EPSG:4326) for mapping, and enforces 
the mandatory D0 100m safety floor.
"""

import csv
import io
import logging

import pandas as pd
from etl.load.loader import load_safety_config

config = load_safety_config()
logger = logging.getLogger(__name__)

# Hard safety floor: no location can ever be shown more precisely than 100m
D0_FLOOR_M = config["generalisation"]["d0_floor_m"]

# Default blur distance for sensitive records when no specific resolution exists
DEFAULT_SENSITIVE_RESOLUTION_M = config["generalisation"][
    "default_sensitive_resolution_m"
]


def generalise_locations(
    df: pd.DataFrame,
    connection,
    easting_column: str,
    northing_column: str,
    resolution_column: str,
) -> pd.DataFrame:
    """
    Generalises and blurs coordinates using PostGIS spatial functions, 
    separating locatable records from missing coordinate entries and 
    preserving original row order.
    """

    if connection is None:
        raise ValueError(
            "A PostGIS database connection is required for location generalisation"
        )

    df = df.copy()

    required_columns = {
        easting_column,
        northing_column,
        resolution_column,
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Calculating resolution:
    # If no resolution exist, fill with 1000m
    # Never allow anything below 100m
    df["effective_resolution_m"] = (
        df[resolution_column]
        .fillna(DEFAULT_SENSITIVE_RESOLUTION_M)
        .clip(lower=D0_FLOOR_M)
    )

    # Flag records with missing coordinates (Returns True or False)
    missing_coordinates = df[easting_column].isna() | df[northing_column].isna()

    if missing_coordinates.any():
        logger.warning(
            "%s records have missing coordinates and will be "
            "excluded from location generalisation. They remain "
            "in the dataset with longitude/latitude set to null.",
            missing_coordinates.sum(),
        )

    # Tag original row order so it can be restored after recombining subsets
    df["_original_row_order"] = range(len(df))

    # Split into locatable rows and rows with missing coordinates
    locatable = df.loc[~missing_coordinates].reset_index(drop=True)
    excluded = df.loc[missing_coordinates].reset_index(drop=True)

    # Insert a temporary row_id to map PostGIS results back accurately
    locatable.insert(0, "row_id", range(len(locatable)))

    # Creates temporary PostgreSQL table
    temp_table = "classified_locations"

    # Prepare only the data required by PostGIS
    location_data = locatable[
        [
            "row_id",
            easting_column,
            northing_column,
            "effective_resolution_m",
        ]
    ].copy()

    # Starts transaction, creates temporary table, then loads data
    # Generalises coordinates
    # If success commit
    if len(location_data) > 0:
        with connection.cursor() as cursor:

            # Creates temporary table in PostgreSQL, when transaction commits, delete
            cursor.execute(
                f"""
                CREATE TEMP TABLE {temp_table} (
                    row_id BIGINT,
                    easting DOUBLE PRECISION,
                    northing DOUBLE PRECISION,
                    resolution_m DOUBLE PRECISION
                )
                ON COMMIT DROP
                """
            )

            # Stream coordinate data into an in-memory CSV buffer for fast COPY loading
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            # Converts DF rows into CSV-like data
            writer.writerows(location_data.itertuples(index=False, name=None))
            # Moves pointer to beginning of the buffer
            buffer.seek(0)

            # Bulk-loads the data with COPY -> Sends all coordinates to PostgreSQL
            with cursor.copy(
                f"""
                COPY {temp_table} (row_id, easting, northing, resolution_m)
                FROM STDIN WITH CSV
                """
            ) as copy:
                copy.write(buffer.getvalue())

            # Execute PostGIS spatial operations: set SRID (BNG 27700),
            # snap points to the resolution grid, transform to WGS84 (4326),
            # and retain snapped BNG coordinates for coarse locality mapping.
            cursor.execute(
                f"""
                SELECT
                    row_id,

                    ST_X(
                        ST_Transform(
                            ST_SnapToGrid(
                                ST_SetSRID(
                                    ST_MakePoint(
                                        easting,
                                        northing
                                    ),
                                    27700
                                ),
                                resolution_m
                            ),
                            4326
                        )
                    ) AS longitude,

                    ST_Y(
                        ST_Transform(
                            ST_SnapToGrid(
                                ST_SetSRID(
                                    ST_MakePoint(
                                        easting,
                                        northing
                                    ),
                                    27700
                                ),
                                resolution_m
                            ),
                            4326
                        )
                    ) AS latitude,

                    -- Snapped (blurred) BNG coordinates, same
                    -- point as above but before the transform to
                    -- lon/lat. coarse_locality must be built from
                    -- THESE, never from the raw easting/northing,
                    -- or the "safe" locality string would leak the
                    -- precise point D0 exists to hide.
                    ST_X(
                        ST_SnapToGrid(
                            ST_SetSRID(
                                ST_MakePoint(
                                    easting,
                                    northing
                                ),
                                27700
                            ),
                            resolution_m
                        )
                    ) AS snapped_easting,

                    ST_Y(
                        ST_SnapToGrid(
                            ST_SetSRID(
                                ST_MakePoint(
                                    easting,
                                    northing
                                ),
                                27700
                            ),
                            resolution_m
                        )
                    ) AS snapped_northing

                FROM {temp_table}
                ORDER BY row_id
                """
            )

            # Fetch the results
            generalised_coordinates = cursor.fetchall()
        connection.commit()
    else:
        generalised_coordinates = []

    # Convert PostGIS results into a DataFrame
    coordinates_df = pd.DataFrame(
        generalised_coordinates,
        columns=[
            "row_id",
            "longitude",
            "latitude",
            "snapped_easting",
            "snapped_northing",
        ],
    )

    # Merge generalised coordinates back to the locatable set using row_id
    locatable = locatable.merge(
        coordinates_df,
        on="row_id",
        how="left",
    ).drop(columns="row_id")

    # Set explicit null coordinates for excluded rows
    excluded["longitude"] = None
    excluded["latitude"] = None
    excluded["snapped_easting"] = None
    excluded["snapped_northing"] = None

    # Recombine locatable and excluded records
    df = pd.concat(
        [locatable, excluded],
        ignore_index=True,
    )

    # Restore original row order and clean up staging helper columns
    df = (
        df.sort_values("_original_row_order")
        .drop(columns="_original_row_order")
        .reset_index(drop=True)
    )

    return df
