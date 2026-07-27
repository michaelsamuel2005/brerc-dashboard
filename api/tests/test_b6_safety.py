"""
B6 safety tests — the fail-closed serving boundary.

These turn the B6 "definition of done" into checks a machine runs, not promises
in a document:
  * the public views expose NONE of the forbidden fields;
  * no public row carries a sub-floor (<100 m) coordinate precision (D0);
  * the read-only API role can read the views but cannot write, and cannot touch
    the base tables at all.

They require the B6 schema (db/b6_schema.sql). Without it — including on a clean
CI runner that only has the B0 sample — they SKIP rather than fail (see the
`needs_b6_schema` marker in conftest.py).
"""

from conftest import needs_b6_schema

from app.db import get_connection

# Fields that must never be reachable through a public view.
FORBIDDEN = {
    "recorder1", "bliss", "eastings", "northings",
    "comments", "precise_date", "is_sensitive", "sensitive",
}
PUBLIC_VIEWS = ["public_species", "public_records", "public_cells", "public_provenance"]
BASE_TABLES = ["species", "occurrence_public", "distribution_cell", "provenance"]
API_ROLE = "brerc_api_ro"


@needs_b6_schema
def test_public_views_expose_no_forbidden_columns():
    with get_connection() as conn, conn.cursor() as cur:
        for view in PUBLIC_VIEWS:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s;",
                (view,),
            )
            columns = {row["column_name"].lower() for row in cur.fetchall()}
            leaked = FORBIDDEN & columns
            assert not leaked, f"{view} leaks forbidden columns: {leaked}"


@needs_b6_schema
def test_no_public_row_is_finer_than_the_100m_floor():
    with get_connection() as conn, conn.cursor() as cur:
        for view in ("public_records", "public_cells"):
            # View names come from a fixed list here, not user input.
            cur.execute(f"SELECT COUNT(*) AS n FROM {view} WHERE precision_metres < 100;")
            n = cur.fetchone()["n"]
            assert n == 0, f"{view} has {n} row(s) finer than the 100 m floor"


@needs_b6_schema
def test_api_role_reads_views_only_and_cannot_write_or_reach_base_tables():
    with get_connection() as conn, conn.cursor() as cur:
        # It can read every public view.
        for view in PUBLIC_VIEWS:
            cur.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT') AS ok;",
                (API_ROLE, view),
            )
            assert cur.fetchone()["ok"], f"{API_ROLE} cannot SELECT {view}"

        # It has no access at all to the base tables — read or write.
        for table in BASE_TABLES:
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute(
                    "SELECT has_table_privilege(%s, %s, %s) AS ok;",
                    (API_ROLE, table, privilege),
                )
                assert not cur.fetchone()["ok"], (
                    f"{API_ROLE} unexpectedly has {privilege} on base table {table}"
                )
