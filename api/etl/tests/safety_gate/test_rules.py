import pandas as pd
import pytest
from unittest.mock import patch

from etl.safety_gate import rules
from etl.safety_gate.rules import (
    SensitiveSpeciesListUnavailable,
    load_sensitive_species,
)


def test_load_sensitive_species_parses_csv_correctly(monkeypatch):
    """
    Confirms the function loads, cleans, and extracts sensitive species and NBN sets.
    Expects two sets containing the valid non-null column values, else fails.
    """
    # Clear the cached result so this test actually executes the function.
    rules.load_sensitive_species.cache_clear()

    # Safely override CONFIG using monkeypatch
    fake_config = {
        "files": {"sensitive_species": {"path": "/absolute/path/to/sensitive.csv"}}
    }
    monkeypatch.setattr(rules, "CONFIG", fake_config)

    mock_df = pd.DataFrame(
        {"species_no": [101, 102, None], "nbn_number": ["NBN1", None, "NBN3"]}
    )

    # Patch pandas.read_csv, clean_data, and file existence checks
    with patch("pandas.read_csv", return_value=mock_df) as mock_read_csv, patch(
        "etl.safety_gate.rules.clean_data", return_value=mock_df
    ) as mock_clean_data, patch("pathlib.Path.exists", return_value=True):

        species_nos, nbn_numbers = load_sensitive_species()

    # Clear the cache so the patched CONFIG does not affect later tests.
    rules.load_sensitive_species.cache_clear()

    mock_read_csv.assert_called_once()
    mock_clean_data.assert_called_once_with(mock_df)

    assert species_nos == {101, 102}
    assert nbn_numbers == {"NBN1", "NBN3"}


def test_load_sensitive_species_refuses_when_no_list_is_available(monkeypatch):
    """
    The gate must fail closed when the list is missing entirely.

    Returning empty sets here would disable the species-list arm of
    classify_chunk() without any signal: every species that is sensitive only
    because BRERC listed it would publish at the 100 m floor instead of 1000 m.
    A missing list must stop the pipeline, not quietly widen what it publishes.
    """
    rules.load_sensitive_species.cache_clear()

    fake_config = {
        "files": {"sensitive_species": {"path": "/absolute/path/to/sensitive.csv"}}
    }
    monkeypatch.setattr(rules, "CONFIG", fake_config)

    # Neither the configured file nor its .example exists.
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(SensitiveSpeciesListUnavailable) as raised:
            load_sensitive_species()

    rules.load_sensitive_species.cache_clear()

    # The message has to tell a maintainer what to do, not just that it broke.
    assert "sensitive.csv" in str(raised.value)
    assert "data/README.md" in str(raised.value)


def test_load_sensitive_species_refuses_a_list_with_no_species_numbers(monkeypatch):
    """
    A file that parses but yields nothing is the same hazard as no file.

    A truncated download or a renamed column produces exactly this, and it
    would otherwise disable the gate just as silently as a missing file.
    """
    rules.load_sensitive_species.cache_clear()

    fake_config = {
        "files": {"sensitive_species": {"path": "/absolute/path/to/sensitive.csv"}}
    }
    monkeypatch.setattr(rules, "CONFIG", fake_config)

    # Right columns, no usable rows — the shape a truncated file actually takes.
    empty_df = pd.DataFrame({"species_no": [None], "nbn_number": [None]})

    with patch("pandas.read_csv", return_value=empty_df), patch(
        "etl.safety_gate.rules.clean_data", return_value=empty_df
    ), patch("pathlib.Path.exists", return_value=True):

        with pytest.raises(SensitiveSpeciesListUnavailable) as raised:
            load_sensitive_species()

    rules.load_sensitive_species.cache_clear()

    assert "species_no" in str(raised.value)


def test_classification_stops_rather_than_publishing_without_the_list(monkeypatch):
    """
    The refusal must reach the caller, not be swallowed on the way.

    This is the property that actually protects wildlife: classify_chunk() is
    the only thing standing between a sensitive record and a 100 m grid square,
    so if the list is unavailable it must raise rather than classify.
    """
    from etl.safety_gate.classification import classify_chunk

    rules.load_sensitive_species.cache_clear()

    fake_config = {
        "files": {"sensitive_species": {"path": "/absolute/path/to/sensitive.csv"}}
    }
    monkeypatch.setattr(rules, "CONFIG", fake_config)

    df = pd.DataFrame(
        {
            "species_no": [101],
            "species_unresolved": [False],
            "record_type": ["field record"],
        }
    )

    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(SensitiveSpeciesListUnavailable):
            classify_chunk(df)

    rules.load_sensitive_species.cache_clear()