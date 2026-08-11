import pandas as pd
from etl.matching.species import normalise_species_name, resolve_species_numbers

# --- Mock data ---

RECORDS_SAMPLE = pd.DataFrame({
    "scientific_name": ["Vulpes vulpes", "  MELES meles ", "Unknown sp", "Meles   meles"]
    # row 0: exact match
    # row 1: extra spaces + different case, should still match via normalisation
    # row 2: no match in dictionary -> unresolved
    # row 3: internal double-space, should still match via normalisation
})

DICTIONARY_SAMPLE = pd.DataFrame({
    "scientific": ["Vulpes vulpes", "Meles meles"],
    "species_no": [101, 102],
    "nbn_number": ["NBN-101", "NBN-102"],
    "common_nam": ["Red fox", "Badger"],
    "taxanb": ["TX101", "TX102"],
})

DICTIONARY_WITH_DUPLICATE_KEY = pd.DataFrame({
    "scientific": ["Vulpes vulpes", "vulpes  vulpes"],  # normalise to same key
    "species_no": [101, 999],
    "nbn_number": ["NBN-101", "NBN-999"],
    "common_nam": ["Red fox", "Red fox duplicate"],
    "taxanb": ["TX101", "TX999"],
})


# --- normalise_species_name tests ---

def test_normalise_species_name_lowercases():
    # Confirms names are lowercased for matching purposes.
    # Expects "vulpes vulpes", else fails.
    result = normalise_species_name(pd.Series(["Vulpes Vulpes"]))
    assert result.iloc[0] == "vulpes vulpes"


def test_normalise_species_name_strips_and_collapses_whitespace():
    # Confirms leading/trailing spaces are stripped and internal
    # multi-spaces collapse to a single space.
    # Expects "vulpes vulpes", else fails.
    result = normalise_species_name(pd.Series(["  Vulpes   Vulpes  "]))
    assert result.iloc[0] == "vulpes vulpes"


# --- resolve_species_numbers tests ---

def test_resolve_species_numbers_matches_exact_name(capsys):
    # Confirms an exact scientific_name match resolves to the correct species_no.
    # Expects species_no 101 for row 0, else fails.
    result = resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    assert result["species_no"].iloc[0] == 101


def test_resolve_species_numbers_matches_despite_case_and_spacing(capsys):
    # Confirms matching is normalisation-aware — case and extra spaces
    # shouldn't prevent a match.
    # Expects species_no 102 for rows 1 and 3, else fails.
    result = resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    assert result["species_no"].iloc[1] == 102
    assert result["species_no"].iloc[3] == 102


def test_resolve_species_numbers_flags_unmatched_as_unresolved(capsys):
    # Confirms a scientific_name with no dictionary match sets
    # species_unresolved = True (D4 fail-closed rule).
    # Expects row 2 unresolved, else fails.
    result = resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    assert result["species_unresolved"].iloc[2] == True


def test_resolve_species_numbers_flags_matched_as_resolved(capsys):
    # Confirms a successfully matched record is NOT flagged unresolved.
    # Expects row 0 resolved (False), else fails.
    result = resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    assert result["species_unresolved"].iloc[0] == False


def test_resolve_species_numbers_preserves_row_count(capsys):
    # Confirms no records are dropped or duplicated during the merge,
    # even when some names don't match (D5 — never silently drop).
    # Expects same row count in and out, else fails.
    result = resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    assert len(result) == len(RECORDS_SAMPLE)


def test_resolve_species_numbers_reports_coverage(capsys):
    # Confirms the D4 coverage summary is printed after resolution.
    # Expects "Species resolution coverage" text present, else fails.
    resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    captured = capsys.readouterr()
    assert "Species resolution coverage" in captured.out


def test_resolve_species_numbers_warns_on_ambiguous_dictionary_keys(capsys):
    # Confirms a warning is printed when two dictionary rows normalise
    # to the same scientific_key (collision), since drop_duplicates()
    # will arbitrarily pick one — this should be visible, not silent.
    # Expects a collision warning in output, else fails.
    resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_WITH_DUPLICATE_KEY)
    captured = capsys.readouterr()
    assert "collisions" in captured.out


def test_resolve_species_numbers_does_not_warn_when_no_collision(capsys):
    # Confirms no collision warning is printed when the dictionary has
    # no ambiguous keys.
    # Expects no "collisions" text in output, else fails.
    resolve_species_numbers(RECORDS_SAMPLE, DICTIONARY_SAMPLE)
    captured = capsys.readouterr()
    assert "collisions" not in captured.out