import pandas as pd
import pytest
from unittest.mock import patch

from etl.profiling.classify import (
    classify_sensitive_species,
)

# --- classify_sensitive_species tests ---

def test_classify_sensitive_species_applies_all_rules():
    # Confirms the function correctly identifies sensitive records based on four distinct rules.
    # Expects 'is_sensitive' to be True if any condition is met, and False otherwise, else fails.
    df = pd.DataFrame({
        "species_no": [100, 200, 200, 200, 200],
        "nbn_number": ["SAFE", "NBN100", "SAFE", "SAFE", "SAFE"],
        "record_type": ["SAFE", "SAFE", "FLAGGED", "SAFE", "SAFE"],
        "species_unresolved": [False, False, False, True, False],
        "scientific_name": ["Species A", "Species B", "Species C", "Species D", "Species E"]
    })

    # Mock the rule constants and suppress print statements to keep test output clean
    with patch("etl.profiling.classify.SENSITIVE_SPECIES_NOS", [100]), \
         patch("etl.profiling.classify.SENSITIVE_NBN_NUMBERS", ["NBN100"]), \
         patch("etl.profiling.classify.FLAGGED_RECORD_TYPES", ["FLAGGED"]), \
         patch("builtins.print"):

        result = classify_sensitive_species(df)

    # First 4 rows trigger one of the 4 rules, last row is completely safe
    assert result["is_sensitive"].tolist() == [True, True, True, True, False]


def test_classify_sensitive_species_detects_mismatch():
    # Confirms the function correctly identifies and logs when species_no and nbn_number disagree.
    # Expects a mismatch warning to be printed without interrupting the data processing, else fails.
    df = pd.DataFrame({
        "species_no": [100],     # Flagged as sensitive
        "nbn_number": ["SAFE"],  # Flagged as safe (Mismatch!)
        "record_type": ["SAFE"],
        "species_unresolved": [False],
        "scientific_name": ["Mismatch Bird"]
    })

    with patch("etl.profiling.classify.SENSITIVE_SPECIES_NOS", [100]), \
         patch("etl.profiling.classify.SENSITIVE_NBN_NUMBERS", ["NBN100"]), \
         patch("etl.profiling.classify.FLAGGED_RECORD_TYPES", ["FLAGGED"]), \
         patch("builtins.print") as mock_print:

        result = classify_sensitive_species(df)

    # The record should still be marked sensitive because at least one rule matched
    assert result["is_sensitive"].tolist() == [True]

    # Verify the sanity check caught the mismatch and printed the warning
    mismatch_logged = any(
        "checks disagree" in call.args[0] 
        for call in mock_print.call_args_list if call.args
    )
    assert mismatch_logged is True


def test_classify_sensitive_species_does_not_modify_original():
    # Confirms the input dataframe is left unchanged (mutation check).
    # Expects the original dataframe to lack the 'is_sensitive' column, else fails.
    df = pd.DataFrame({
        "species_no": [200],
        "nbn_number": ["SAFE"],
        "record_type": ["SAFE"],
        "species_unresolved": [False],
        "scientific_name": ["Safe Bird"]
    })

    with patch("etl.profiling.classify.SENSITIVE_SPECIES_NOS", [100]), \
         patch("etl.profiling.classify.SENSITIVE_NBN_NUMBERS", ["NBN100"]), \
         patch("etl.profiling.classify.FLAGGED_RECORD_TYPES", ["FLAGGED"]), \
         patch("builtins.print"):

        classify_sensitive_species(df)

    assert "is_sensitive" not in df.columns