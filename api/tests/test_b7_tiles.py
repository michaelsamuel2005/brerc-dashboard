"""
B7 tile-function tests — proves the Martin function source produces real,
safe vector tiles. Needs db/b7_tiles.sql loaded (skips otherwise, like the
other DB-backed tests).
"""

from conftest import needs_b7_tiles

from app.db import get_connection

# A z=8 tile over Bristol (where the sample cells are) vs one over the Pacific.
BRISTOL_TILE = (8, 126, 85)
FARAWAY_TILE = (8, 10, 120)


@needs_b7_tiles
def test_tile_over_data_has_content():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT length(cells_tile(%s, %s, %s)) AS n;", BRISTOL_TILE)
        assert cur.fetchone()["n"] > 0, "Expected a non-empty tile where cells exist"


@needs_b7_tiles
def test_tile_away_from_data_is_empty():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT length(cells_tile(%s, %s, %s)) AS n;", FARAWAY_TILE)
        assert cur.fetchone()["n"] == 0, "A tile with no cells should be empty"


@needs_b7_tiles
def test_readonly_role_can_execute_tile_function():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT has_function_privilege("
            "'brerc_api_ro', 'cells_tile(integer,integer,integer,json)', 'EXECUTE') AS ok;"
        )
        assert cur.fetchone()["ok"], "The read-only tile role must be able to run cells_tile"
