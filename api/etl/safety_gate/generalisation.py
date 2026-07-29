# etl/safety_gate/generalise.py
"""
    Snaps easting/northing to a resolution grid in PostGIS (BNG ->
    WGS84), enforcing the D0 100m floor. Records with missing
    coordinates are kept (for record counts) but returned with null
    longitude/latitude - downstream public-output code must filter
    these out before anything reaches a map. Original row order is
    preserved on return.
"""

import csv
import io
import logging

import pandas as pd
from etl.config.loader import load_safety_config

config = load_safety_config()
logger = logging.getLogger(__name__)

# Hard safety floor: no location can ever be shown more precisely than 100m
D0_FLOOR_M = config["generalisation"]["d0_floor_m"]

# Default blur distance for sensitive records when no specific resolution exists
DEFAULT_SENSITIVE_RESOLUTION_M = config["generalisation"]["default_sensitive_resolution_m"]

# Connection allows python to send SQL to PostGIS/PostgreSQL
def generalise_locations(
    df: pd.DataFrame,
    connection,
    easting_column: str,
    northing_column: str,
    resolution_column: str,
) -> pd.DataFrame:

    if connection is None:
        raise ValueError(
            "A PostGIS database connection is required"
            "for location generalisation"
        )

    df = df.copy()

    required_columns = {
        easting_column,
        northing_column,
        resolution_column,
    }

    missing_columns = required_columns - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    # Calculating resolution:
    # If no resolution exist, fill with 10000m
    # Never allow anything below 100m
    df["effective_resolution_m"] = (
        df[resolution_column]
        .fillna(DEFAULT_SENSITIVE_RESOLUTION_M)
        .clip(lower=D0_FLOOR_M)
    )

    # Checks for any missing coordinates -> Returns T or F
    missing_coordinates = (
        df[easting_column].isna()
        | df[northing_column].isna()
    )

    # Using logging to capture error
    if missing_coordinates.any():
        logger.warning(
            "%s records have missing coordinates and will be "
            "excluded from location generalisation. They remain "
            "in the dataset with longitude/latitude set to null.",
            missing_coordinates.sum(),
        )

    # Tag original row order before splitting, so it can be restored
    # after the two subsets are recombined at the end.
    df["_original_row_order"] = range(len(df))

    # Split the chunk: only rows with real coordinates go through
    # PostGIS. Rows with missing coordinates are kept (for accurate
    # record counts) but never get a lon/lat.
    locatable = df.loc[~missing_coordinates].reset_index(drop=True)
    excluded = df.loc[missing_coordinates].reset_index(drop=True)

    # Assign row_id on the locatable subset - this is the key used to
    # join PostGIS results back, since locatable no longer necessarily
    # aligns 1:1-by-position with the original df.
    locatable.insert(0, "row_id", range(len(locatable)))

    # Creates temporary PostgreSQL table (Adjust later maybe)
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
        with connection:
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

                # Creates in-memory text buffer
                buffer = io.StringIO()
                writer = csv.writer(buffer)
                # Converts DF rows into CSV-like data
                writer.writerows(
                    location_data.itertuples(index=False, name=None)
                )
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

                # Generalise the whole chunk in PostGIS
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

    # Join safe coordinates back to the locatable rows by row_id (key),
    # not by position - locatable and coordinates_df share row_id.
    locatable = locatable.merge(
        coordinates_df,
        on="row_id",
        how="left",
    ).drop(columns="row_id")

    # Excluded rows get explicit null coordinates so downstream code
    # can filter on them rather than relying on a column being absent.
    excluded["longitude"] = None
    excluded["latitude"] = None
    excluded["snapped_easting"] = None
    excluded["snapped_northing"] = None

    # Recombine - full record count preserved, only the excluded rows
    # carry null lon/lat. It is the public-output layer's job to make
    # sure these never reach a public map.
    df = pd.concat(
        [locatable, excluded],
        ignore_index=True,
    )

    # Restore original row order, then drop the ordering key.
    df = (
        df
        .sort_values("_original_row_order")
        .drop(columns="_original_row_order")
        .reset_index(drop=True)
    )

    return df