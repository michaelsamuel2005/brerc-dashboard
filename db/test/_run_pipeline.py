"""
Helper for run_e2e.py — runs one ETL pass against the two throwaway databases.

Run as a separate process on purpose. The ETL reads its configuration at import
time, so a fresh process is the only reliable way to run it twice (initial load,
then incremental) with the same settings.

SAFETY: this writes a temporary config/safety.yaml. If you already have one — and
it may hold a real database password — it is moved aside first and restored
afterwards, even if the run fails.
"""

import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO / "config" / "safety.yaml"
BACKUP_PATH = REPO / "config" / "safety.yaml.e2e-backup"
SENSITIVE_CSV = REPO / "db" / "test" / "e2e_sensitive_species.csv"

SOURCE_URL = os.environ["E2E_SOURCE_URL"]
UI_URL = os.environ["E2E_UI_URL"]

# Test configuration. Points the pipeline at the mock source view and the
# throwaway UI database, and otherwise keeps BRERC's real rules: 1 km blurring
# for sensitive records, 100 m floor.
TEST_CONFIG = f"""
files:
  sensitive_species:
    path: "{SENSITIVE_CSV.as_posix()}"

connection:
  dbname: e2e_source

destination:
  dbname: e2e_ui
  schema: public
  table: occurrence_public

admin:
  dbname: e2e_ui

load:
  incremental_check: true

source:
  mode: "database"
  records_query: "SELECT * FROM brerc_source.vw_occurrences"
  dictionary_query: "SELECT * FROM brerc_source.vw_species_dictionary"

columns:
  species_number: species_no
  nbn_number: nbn_number
  verified: verified
  eastings: eastings
  northings: northings
  record_date: date_of_record
  modified_date: date_mdb_modified

reconciliation:
  hash_columns:
    - scientific_name
    - record_type
    - verified
    - eastings
    - northings

generalisation:
  d0_floor_m: 100
  default_sensitive_resolution_m: 1000

aggregation:
  suppression_threshold: 1
  cell_size_m: 1000

species_resolutions: {{}}

verified_values:
  accepted:
    - "Accepted - correct"
    - "Accepted - considered correct"
    - "Accepted"
  legacy:
    - "BRERC"

# Feature-based sensitivity. BRERC supply the authoritative list in their
# 'Drop Down list'; these are the entries the test data exercises.
flagged_record_types:
  - sett
  - holt
  - maternity roost
  - bat roost
  - nest
"""

had_existing = CONFIG_PATH.exists()
try:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if had_existing:
        shutil.move(str(CONFIG_PATH), str(BACKUP_PATH))
    CONFIG_PATH.write_text(TEST_CONFIG, encoding="utf-8")

    # The ETL's own env overrides. Note there are THREE different names for the
    # three connections — SOURCE_DATABASE_URL (etl/db.py),
    # DESTINATION_DATABASE_URL / DATABASE_URL (etl/db.py), and
    # DATABASE_URL_ADMIN (etl/load/reload.py, which does the DDL). Miss the last
    # one and the run fails only when it tries a full reload.
    os.environ["SOURCE_DATABASE_URL"] = SOURCE_URL
    os.environ["DESTINATION_DATABASE_URL"] = UI_URL
    os.environ["DATABASE_URL"] = UI_URL
    os.environ["DATABASE_URL_ADMIN"] = UI_URL

    sys.path.insert(0, str(REPO / "api"))
    from etl.job import nightly_job

    nightly_job()
    print("PIPELINE RUN COMPLETE")

finally:
    # Always put the developer's own config back, even if the run blew up.
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    if had_existing and BACKUP_PATH.exists():
        shutil.move(str(BACKUP_PATH), str(CONFIG_PATH))
