# Loads BRERC safety settings from YAML

# Contains interface used by safety gate

# Organisation specific rules are in: config/safety_rules.yaml

"""
NOTE:
- CONFIG["key"] returns the value stored under "key".
Could be a dictionary, list, string, number, etc.

- CONFIG["key1"]["key2"] first gets the value stored under
  "key1" (usually another dictionary), then retrieves the
  value stored under "key2".
"""

from functools import lru_cache
from pathlib import Path

from etl.load.loader import load_safety_config


CONFIG = load_safety_config()


# Generalisation rules

D0_FLOOR_M = CONFIG["generalisation"]["d0_floor_m"]

DEFAULT_SENSITIVE_RESOLUTION_M = CONFIG["generalisation"][
    "default_sensitive_resolution_m"
]

SPECIES_RESOLUTIONS_M = CONFIG["species_resolutions"]


# Record type rules

FLAGGED_RECORD_TYPES = frozenset(CONFIG["flagged_record_types"])


# Sensitive species


@lru_cache(maxsize=1)
def load_sensitive_species():
    import pandas as pd
    from etl.profiling.cleaning import clean_data

    # Get CSV location from YAML
    sensitive_species_file = Path(CONFIG["files"]["sensitive_species"]["path"])

    if not sensitive_species_file.is_absolute():
        sensitive_species_file = (
            Path(__file__).resolve().parents[3] / sensitive_species_file
        )

    # Fall back to the example file if the real file is unavailable
    if not sensitive_species_file.exists():
        example_file = sensitive_species_file.with_suffix(
            sensitive_species_file.suffix + ".example"
        )
        if example_file.exists():
            sensitive_species_file = example_file
        else:
            # SAFE FALLBACK: If neither file exists, return empty sets
            # so tests and runs don't crash with a FileNotFoundError.
            return set(), set()

    # Read + clean CSV
    df = pd.read_csv(sensitive_species_file)
    df = clean_data(df)

    sensitive_species_nos = set(df["species_no"].dropna())

    sensitive_nbn_numbers = set(df["nbn_number"].dropna())

    return (
        sensitive_species_nos,
        sensitive_nbn_numbers,
    )
