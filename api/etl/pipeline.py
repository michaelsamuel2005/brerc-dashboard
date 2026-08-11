# TODO: pipeline currently broken after restructure — fix imports before next run.
# 1. `from cleaning import clean_data` -> `from etl.profiling.cleaning import clean_data`
# 2. `from etl.profiling.filtering import filter_sensitive_species` -> function doesn't
#    exist under that name. Two candidate classifiers currently live in different files:
#      - etl/profiling/filtering.py :: classify_sensitive_species  (has NBN-number check)
#      - etl/safety_gate/classify.py :: classify_chunk              (has blur/resolution_m,
#        missing NBN-number check)
#    These need merging (D4 requires the NBN check; downstream needs blur/resolution_m).
#    Until merged, pick ONE to wire in here — see safety_gate/classify.py for the
#    fuller TODO on what's missing from each.
# 3. Also delete stale etl/__pycache__/rules.cpython-313.pyc (leftover from before
#    rules.py moved into safety_gate/)



# pipeline.py
from etl.profiling.cleaning import clean_data
from etl.safety_gate.classification import classify_chunk  # switched to this one

def run_pipeline(df):

    df = clean_data(df)          # clean first

    df = classify_chunk(df)      # then classify — order matters, see below
    return df