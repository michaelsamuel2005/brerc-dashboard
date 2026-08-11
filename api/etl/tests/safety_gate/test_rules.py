import pandas as pd
from unittest.mock import patch

from etl.safety_gate import rules
from etl.safety_gate.rules import load_sensitive_species


def test_load_sensitive_species_parses_csv_correctly(monkeypatch):
    # Confirms the function loads, cleans, and extracts sensitive species and NBN sets.
    # Expects two sets containing the valid non-null column values, else fails.

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
        "etl.profiling.cleaning.clean_data", return_value=mock_df
    ) as mock_clean_data, patch("pathlib.Path.exists", return_value=True):

        species_nos, nbn_numbers = load_sensitive_species()

    # Clear the cache so the patched CONFIG does not affect later tests.
    rules.load_sensitive_species.cache_clear()

    mock_read_csv.assert_called_once()
    mock_clean_data.assert_called_once_with(mock_df)

    assert species_nos == {101, 102}
    assert nbn_numbers == {"NBN1", "NBN3"}
