"""
Loads and exposes BRERC safety settings, spatial generalisation rules, 
flagged record types, and cached sensitive species lists from configuration files.
"""

from functools import lru_cache
from pathlib import Path

import pandas as pd
import etl.columns as C
from etl.columns import ColumnMappingError, to_pipeline_names
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


class SensitiveSpeciesListUnavailable(RuntimeError):
    """The sensitive-species list could not be loaded, so publishing must stop.

    Raised instead of returning an empty list. An empty list is not a neutral
    starting point here: it silently disables the species-list arm of
    classify_chunk(), and every species that is sensitive ONLY because BRERC
    listed it — rather than because the source flagged it or its record type is
    flagged — is then published at the 100 m floor instead of 1000 m. That is
    the category most likely to hold badger setts and Schedule 1 nest sites.

    A crash is recoverable. A public map showing precise setts is not.
    """


@lru_cache(maxsize=1)
def load_sensitive_species():
    """
    Loads, cleans, and caches sensitive species numbers and NBN numbers
    from the configured CSV file.

    FAILS CLOSED. If the list cannot be found, or loads with no species numbers
    in it, this raises SensitiveSpeciesListUnavailable rather than returning
    empty sets. Refusing to run is the safe outcome; running without the list
    looks identical to running with it, right up until the map is published.

    If you hit this while developing: put a CSV at the path named in
    config/safety.yaml (default data/sensitive_species.csv) with a species_no
    column, or place a data/sensitive_species.csv.example alongside it. The
    data/ folder is git-ignored precisely so real BRERC lists never reach
    GitHub — see data/README.md.
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
            raise SensitiveSpeciesListUnavailable(
                f"No sensitive-species list found at {sensitive_species_file} "
                f"(and no {example_file.name} beside it). The safety gate cannot "
                "classify protected species without it, so the pipeline stops "
                "here rather than publishing at the 100 m floor. See "
                "data/README.md for how to supply the file locally."
            )

    # Read the list and translate BRERC's column names to the pipeline's
    # (safety.yaml 'sensitive_species_columns:').
    #
    # Both columns are required, not just species_no. classify_chunk() uses
    # the species_no set, and profiling.classify uses the nbn_number set for
    # its mismatch check — a renamed or blanked nbn_number column would
    # silently hand that check an empty set. A mapping problem is reported as
    # the species list being unavailable, not as a SOURCE data problem, so
    # describe_failure() points staff at the right file.
    df = clean_data(pd.read_csv(sensitive_species_file))

    try:
        df = to_pipeline_names(
            df,
            "sensitive_species_columns",
            required=C.SENSITIVE_SPECIES_COLUMNS_REQUIRED,
            what=f"the sensitive-species list at {sensitive_species_file}",
        )
    except ColumnMappingError as error:
        raise SensitiveSpeciesListUnavailable(str(error)) from error

    sensitive_species_nos = set(df[C.SPECIES_NO].dropna())
    sensitive_nbn_numbers = set(df[C.NBN_NUMBER].dropna())

    # A file that parses but yields no values is the same hazard as no file at
    # all — a truncated download would otherwise sail through and disable the
    # gate (or profiling's mismatch check) just as quietly.
    if not sensitive_species_nos:
        raise SensitiveSpeciesListUnavailable(
            f"The sensitive-species list at {sensitive_species_file} loaded but "
            "contains no usable species_no values. Check the file is complete."
        )
    if not sensitive_nbn_numbers:
        raise SensitiveSpeciesListUnavailable(
            f"The sensitive-species list at {sensitive_species_file} loaded but "
            "contains no usable nbn_number values. Check the file is complete."
        )

    return (
        sensitive_species_nos,
        sensitive_nbn_numbers,
    )
