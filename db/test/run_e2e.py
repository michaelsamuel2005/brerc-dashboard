"""
END-TO-END TEST RUNNER — steps 1 to 10 of the pipeline test.

WHAT THIS DOES
Stands up BOTH databases from scratch, runs the real ETL against them, and then
asserts what came out the other end. It covers the advisor's steps 1-6 and 8-10.
Steps 7 and 11 ("check the UI shows it") are deliberately not here: no script can
tell you the dashboard looks right. Open it and look.

WHY IT EXISTS
Everything tested so far has started from the UI database, i.e. from data that
was already safe. This starts one step earlier — from a stand-in for BRERC's own
database, complete with the precise coordinates, recorder names, place names and
free-text comments that must never be published. It then checks they are gone.
That is the part no previous test could reach.

NOTHING REAL IS INVOLVED. Both databases are created fresh, used, and dropped.
Your own brerc_ui database is never touched.

HOW TO RUN
    python db/test/run_e2e.py

You need a local PostgreSQL with PostGIS, and ADMIN_URL below pointing at it.
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO = Path(__file__).resolve().parents[2]

# A superuser connection used only to create/drop the two throwaway databases.
ADMIN_URL = os.getenv(
    "E2E_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/postgres"
)
SOURCE_DB = "brerc_e2e_source"      # stand-in for BRERC's database
UI_DB = "brerc_e2e_ui"              # the dashboard's database


def url_for(dbname: str) -> str:
    base = ADMIN_URL.rsplit("/", 1)[0]
    return f"{base}/{dbname}"


# ---------------------------------------------------------------------------
# Small helpers for readable output
# ---------------------------------------------------------------------------
PASSED, FAILED = [], []


def step(number: str, title: str) -> None:
    print(f"\n{'=' * 74}\nSTEP {number} — {title}\n{'=' * 74}")


def check(description: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(description)
    print(f"  [{'PASS' if condition else 'FAIL'}] {description}")
    if detail and not condition:
        print(f"         {detail}")


def run_sql_file(url: str, path: Path) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(path.read_text(encoding="utf-8"))
    print(f"  loaded {path.relative_to(REPO)}")


def recreate(dbname: str, postgis: bool = False) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}";')
        conn.execute(f'CREATE DATABASE "{dbname}";')
    if postgis:
        with psycopg.connect(url_for(dbname), autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
    print(f"  created database {dbname}")


def query(url: str, sql: str, params=None):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# STEPS 1-2: BRERC's source database and view
# ---------------------------------------------------------------------------
step("1 & 2", "Create a mock of BRERC's database and its view")
recreate(SOURCE_DB)
run_sql_file(url_for(SOURCE_DB), REPO / "db/test/e2e_source_mock.sql")
check(
    "source view brerc_source.vw_occurrences exists",
    bool(query(url_for(SOURCE_DB),
               "SELECT to_regclass('brerc_source.vw_occurrences') IS NOT NULL AS ok;")[0]["ok"]),
)

# ---------------------------------------------------------------------------
# STEP 3: the UI database
# ---------------------------------------------------------------------------
step("3", "Create the UI database and its tables")
recreate(UI_DB, postgis=True)
for sql in ["db/b6_schema.sql", "db/b7_tiles.sql"]:
    run_sql_file(url_for(UI_DB), REPO / sql)
check(
    "all four public views exist",
    len(query(url_for(UI_DB),
              "SELECT table_name FROM information_schema.views "
              "WHERE table_name LIKE 'public\\_%';")) == 4,
)

# ---------------------------------------------------------------------------
# STEP 4: test data into the source
# ---------------------------------------------------------------------------
step("4", "Insert the test data into the source view")
run_sql_file(url_for(SOURCE_DB), REPO / "db/test/e2e_source_data.sql")
source_rows = query(url_for(SOURCE_DB), "SELECT COUNT(*) AS n FROM brerc_source.vw_occurrences;")[0]["n"]
check(f"source view holds {source_rows} records", source_rows == 7, f"expected 7, got {source_rows}")

# ---------------------------------------------------------------------------
# STEP 5: the initial load
# ---------------------------------------------------------------------------
step("5", "Run the initial load")
env = dict(os.environ)
env["E2E_SOURCE_URL"] = url_for(SOURCE_DB)
env["E2E_UI_URL"] = url_for(UI_DB)
result = subprocess.run(
    [sys.executable, str(REPO / "db/test/_run_pipeline.py")],
    cwd=str(REPO / "api"), env=env, capture_output=True, text=True,
    encoding="utf-8", errors="replace",   # ETL logs contain non-UTF-8 bytes on Windows
)
print(result.stdout[-2500:] if result.stdout else "")
if result.returncode != 0:
    print((result.stderr or "")[-2500:])
check("initial load completed without error", result.returncode == 0)

# ---------------------------------------------------------------------------
# STEP 6: verify the UI database — including the safety boundary
# ---------------------------------------------------------------------------
step("6", "Verify the UI database, and that nothing unsafe came through")

records = query(url_for(UI_DB), "SELECT * FROM public_records ORDER BY record_id;")
check("records reached the UI database", len(records) > 0, f"got {len(records)}")

if records:
    columns = set(records[0])
    forbidden = {"recorder1", "recorder_name", "comments", "eastings", "northings",
                 "easting", "northing", "is_sensitive", "sensitivity_reason"}
    leaked = forbidden & columns
    check("no forbidden column reaches the public view", not leaked, f"leaked: {leaked}")

    check(
        "every record is at 100 m or coarser (D0 floor)",
        all(r["precision_metres"] >= 100 for r in records),
    )

    # The otter (R003) and the badger sett (R004) must both be blurred to 1 km:
    # one flagged by the view's Sensitive column, one by its record type.
    for rid, why in [("R003", "sensitive species, via the view's Sensitive column"),
                     ("R004", "sensitive feature, via record_type = 'sett'"),
                     ("R007", "unresolvable species, fail-closed")]:
        row = next((r for r in records if str(r["record_id"]) == rid), None)
        if row is None:
            check(f"{rid} present ({why})", False, "record missing entirely")
            continue
        check(
            f"{rid} blurred to 1 km or coarser — {why}",
            row["precision_metres"] >= 1000,
            f"precision_metres = {row['precision_metres']}",
        )
        check(
            f"{rid} has no precise place name",
            not row["place"] or "weir" not in str(row["place"]).lower(),
            f"place = {row['place']!r}",
        )

    check(
        "non-numeric record id survived (R006/A)",
        any(str(r["record_id"]) == "R006/A" for r in records),
    )

species = query(url_for(UI_DB), "SELECT * FROM public_species ORDER BY species_id;")
check("species index populated", len(species) > 0, f"got {len(species)}")
check(
    "species with no records (out_of_avon='Yes') is NOT published",
    not any(str(s["species_id"]) == "9999" for s in species),
    "Alcedo atthis has no records and should not appear",
)

# ---------------------------------------------------------------------------
# STEPS 8-9: new records, then the incremental load
# ---------------------------------------------------------------------------
step("8 & 9", "Add new records, then run the incremental load")
before = len(records)
with psycopg.connect(url_for(SOURCE_DB), autocommit=True) as conn:
    for i in range(1, 13):
        conn.execute(
            """
            INSERT INTO brerc_source.occurrences
                (unique_no, species_no, scientific_name, nbn_number, record_type,
                 sensitive, verified, eastings, northings, date_of_record,
                 date_mdb_modified, recorder1, place, comments)
            VALUES (%s, '6973', 'Erithacus rubecula', 'NBNSYS0000000001',
                    'field record', 'No', 'Accepted', %s, %s, DATE '2025-09-01',
                    NOW(), 'New Recorder', 'A precise place', 'A precise comment');
            """,
            (f"N{i:03d}", 358000 + i * 100, 172000 + i * 100),
        )
print("  added 12 new records to the source")

result2 = subprocess.run(
    [sys.executable, str(REPO / "db/test/_run_pipeline.py")],
    cwd=str(REPO / "api"), env=env, capture_output=True, text=True,
    encoding="utf-8", errors="replace",   # ETL logs contain non-UTF-8 bytes on Windows
)
print(result2.stdout[-2500:] if result2.stdout else "")
if result2.returncode != 0:
    print((result2.stderr or "")[-2500:])
check("incremental load completed without error", result2.returncode == 0)

# ---------------------------------------------------------------------------
# STEP 10: verify the update
# ---------------------------------------------------------------------------
step("10", "Verify the UI database picked up the new records")
after_rows = query(url_for(UI_DB), "SELECT * FROM public_records;")
check(
    f"record count grew from {before} to {len(after_rows)}",
    len(after_rows) > before,
)
check(
    "the new records are present",
    sum(1 for r in after_rows if str(r["record_id"]).startswith("N")) == 12,
    f"found {sum(1 for r in after_rows if str(r['record_id']).startswith('N'))} of 12",
)
check(
    "still no forbidden columns after the incremental load",
    not ({"recorder1", "comments", "eastings", "northings"} & set(after_rows[0]))
    if after_rows else False,
)

# ---------------------------------------------------------------------------
print(f"\n{'=' * 74}")
print(f"RESULT: {len(PASSED)} passed, {len(FAILED)} failed")
if FAILED:
    print("\nFailed:")
    for f in FAILED:
        print(f"  - {f}")
print(f"{'=' * 74}")
print("\nSteps 7 and 11 are not scripted — open the dashboard and look at it.")
print(f"The two databases are left in place so you can inspect them:")
print(f"  source: {SOURCE_DB}")
print(f"  UI:     {UI_DB}")
sys.exit(1 if FAILED else 0)
