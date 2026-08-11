"""
Loads and exposes BRERC safety settings, spatial generalisation rules, 
flagged record types, and cached sensitive species lists from configuration files.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
from etl.load.loader import load_safety_config
from etl.profiling.cleaning import clean_data

CONFIG = load_safety_config()


# Generalisation rules

D0_FLOOR_M = CONFIG["generalisation"]["d0_floor_m"]

DEFAULT_SENSITIVE_RESOLUTION_M = CONFIG["generalisation"][
    "default_sensitive_resolution_m"
]

SPECIES_RESOLUTIONS_M = CONFIG["species_resolutions"]

# Record type rules
FLAGGED_RECORD_TYPES = frozenset(CONFIG["flagged_record_types"])


@lru_cache(maxsize=1)
def load_sensitive_species():
    """
    Loads, cleans, and caches sensitive species numbers and NBN numbers 
    from the configured CSV file, falling back to an example file or empty sets if missing.
    """

    # Resolve sensitive species file path from YAML configuration
    sensitive_species_file = Path(CONFIG["files"]["sensitive_species"]["path"])

    if not sensitive_species_file.is_absolute():
        sensitive_species_file = (
            Path(__file__).resolve().parents[3] / sensitive_species_file
        )

    # Fall back to an example file if the primary sensitive species file is unavailable
    if not sensitive_species_file.exists():
        example_file = sensitive_species_file.with_suffix(
            sensitive_species_file.suffix + ".example"
        )
        if example_file.exists():
            sensitive_species_file = example_file
        else:
            # Safe fallback: return empty sets so tests and
            # pipelines don't crash with FileNotFoundError
            return set(), set()

    # Read and clean the sensitive species CSV data
    df = pd.read_csv(sensitive_species_file)
    df = clean_data(df)

    sensitive_species_nos = set(df["species_no"].dropna())
    sensitive_nbn_numbers = set(df["nbn_number"].dropna())

    return (
        sensitive_species_nos,
        sensitive_nbn_numbers,
    )
