import pandas as pd
import pytest
from unittest.mock import patch

from etl.safety_gate import rules
from etl.safety_gate.rules import ( # Update with your actual module path if different
    load_sensitive_species,
)


def test_load_sensitive_species_parses_csv_correctly(monkeypatch):
    # Confirms the function loads, cleans, and extracts sensitive species and NBN sets.
    # Expects two sets containing the valid non-null column values, else fails.
    
    # Safely override CONFIG using monkeypatch
    fake_config = {
        "files": {
            "sensitive_species": {
                "path": "/absolute/path/to/sensitive.csv"
            }
        }
    }
    monkeypatch.setattr(rules, "CONFIG", fake_config)

    mock_df = pd.DataFrame({
        "species_no": [101, 102, None],
        "nbn_number": ["NBN1", None, "NBN3"]
    })

    # Patch pandas.read_csv and clean_data at their source modules
    with patch("pandas.read_csv", return_value=mock_df) as mock_read_csv, \
         patch("etl.profiling.cleaning.clean_data", return_value=mock_df) as mock_clean_data:

        species_nos, nbn_numbers = load_sensitive_species()

        mock_read_csv.assert_called_once()
        mock_clean_data.assert_called_once()
        
        assert species_nos == {101, 102}
        assert nbn_numbers == {"NBN1", "NBN3"}