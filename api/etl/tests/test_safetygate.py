"""
    Unit tests for B2's Done bar:
      - Every sensitive species generalises, including a synonym.
      - Every sensitive record type generalises.
      - Fail-closed on unclassifiable.
      - No record finer than its floor.
"""

import pandas as pd
import pytest

from etl.safety_gate import classify
from etl.matching.species import resolve_species_numbers
from etl.safety_gate.rules import (
    DEFAULT_SENSITIVE_RESOLUTION_M, D0_FLOOR_M
)

SENSITIVE_SPECIES_NO = 12345
SENSITIVE_RECORD_TYPE = "Bat roost"


@pytest.fixture(autouse=True)
def patch_rules(monkeypatch):
    # classify_chunk checks against SENSITIVE_SPECIES_NOS /
    # FLAGGED_RECORD_TYPES as names already imported into classify.py
    # at module load time - patching them on rules.py would NOT
    # affect classify.py's copy, so they must be patched on the
    # classify module itself.
    monkeypatch.setattr(
        classify, "SENSITIVE_SPECIES_NOS", {SENSITIVE_SPECIES_NO}
    )
    monkeypatch.setattr(
        classify, "FLAGGED_RECORD_TYPES", {SENSITIVE_RECORD_TYPE}
    )


@pytest.fixture
def dictionary_df():
    # Canonical name + a synonym, both resolving to the same
    # sensitive species_no.
    return pd.DataFrame({
        "scientific": ["Myotis daubentonii", "Vespertilio daubentonii"],
        "species_no": [SENSITIVE_SPECIES_NO, SENSITIVE_SPECIES_NO],
        "nbn_number": ["NBN001", "NBN001"],
    })


def _classify(records_df, dictionary_df):
    resolved = resolve_species_numbers(records_df, dictionary_df)
    return classify.classify_chunk(resolved)


# --- Sensitive species, including a synonym, generalises ---

def test_sensitive_species_canonical_name_generalises(dictionary_df):
    records = pd.DataFrame({
        "scientific_name": ["Myotis daubentonii"],
        "record_type": ["Casual record"],
    })
    result = _classify(records, dictionary_df)

    assert result.loc[0, "is_sensitive"] == True
    assert result.loc[0, "blurred"] == True
    assert result.loc[0, "sensitivity_reason"] == "sensitive_species"
    assert result.loc[0, "resolution_m"] >= D0_FLOOR_M


def test_sensitive_species_synonym_generalises(dictionary_df):
    # Same species, entered under its synonym - must still be caught.
    records = pd.DataFrame({
        "scientific_name": ["Vespertilio daubentonii"],
        "record_type": ["Casual record"],
    })
    result = _classify(records, dictionary_df)

    assert result.loc[0, "species_unresolved"] == False
    assert result.loc[0, "is_sensitive"] == True
    assert result.loc[0, "sensitivity_reason"] == "sensitive_species"
    assert result.loc[0, "resolution_m"] >= D0_FLOOR_M


# --- Sensitive record type generalises, regardless of species ---

def test_sensitive_record_type_generalises_with_common_species(dictionary_df):
    # Common, non-sensitive species - but a flagged record type
    # (e.g. a roost) must still trigger sensitivity.
    common_species = pd.DataFrame({
        "scientific": ["Pipistrellus pipistrellus"],
        "species_no": [99999],
        "nbn_number": ["NBN999"],
    })
    records = pd.DataFrame({
        "scientific_name": ["Pipistrellus pipistrellus"],
        "record_type": [SENSITIVE_RECORD_TYPE],
    })
    result = _classify(records, common_species)

    assert result.loc[0, "is_sensitive"] == True
    assert result.loc[0, "blurred"] == True
    assert result.loc[0, "sensitivity_reason"] == "sensitive_record_type"
    assert result.loc[0, "resolution_m"] >= D0_FLOOR_M


# --- Fail-closed on unclassifiable ---

def test_unresolved_species_fails_closed(dictionary_df):
    records = pd.DataFrame({
        "scientific_name": ["Nonexistent madeupii"],
        "record_type": ["Casual record"],
    })
    result = _classify(records, dictionary_df)

    assert result.loc[0, "species_unresolved"] == True
    assert result.loc[0, "is_sensitive"] == True
    assert result.loc[0, "blurred"] == True
    assert result.loc[0, "sensitivity_reason"] == "unresolved_species"
    assert result.loc[0, "resolution_m"] == DEFAULT_SENSITIVE_RESOLUTION_M


# --- No record finer than its floor ---

def test_no_resolution_below_floor(dictionary_df):
    records = pd.DataFrame({
        "scientific_name": [
            "Myotis daubentonii",         # sensitive species
            "Vespertilio daubentonii",    # synonym of same
            "Pipistrellus pipistrellus",  # unlisted -> unresolved
            "Nonexistent madeupii",       # unresolved
        ],
        "record_type": [
            "Casual record",
            SENSITIVE_RECORD_TYPE,
            "Casual record",
            "Casual record",
        ],
    })
    result = _classify(records, dictionary_df)

    assert (result["resolution_m"] >= D0_FLOOR_M).all()