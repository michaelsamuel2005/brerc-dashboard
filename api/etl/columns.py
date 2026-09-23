"""
The pipeline's own column names, and the one place BRERC's names are
translated into them.

BRERC's column names live ONLY in config/safety.yaml. Straight after the
source is read, to_pipeline_names() renames the configured columns to the
names below and drops every other column. From then on the pipeline only
ever sees these names, so a column BRERC renames is a one-line change to
safety.yaml, never a code change.

Each constant is the left-hand side of a mapping in safety.yaml:

    columns:              occurrence records   (the source view)
    dictionary_columns:   species dictionary
    sensitive_species_columns:  BRERC's sensitive-species list

The column names of our own brerc_ui tables (record_id, precision_metres ...)
are our schema, not BRERC's, and stay in the code that writes them.
"""

import pandas as pd

from etl.load.loader import load_safety_config

CONFIG = load_safety_config()


# --- Occurrence records ------------------------------------------------------

UNIQUE_NO = "unique_no"
SCIENTIFIC_NAME = "scientific_name"
COMMON_NAME = "common_name"
SPECIES_NO = "species_no"
RECORD_TYPE = "record_type"
VERIFIED = "verified"
EASTING = "easting"  # PRECISE — generalised, never published
NORTHING = "northing"  # PRECISE — generalised, never published
DATE_OF_RECORD = "date_of_record"
MODIFIED_DATE = "modified_date"
SOURCE_YEAR = "source_year"
SENSITIVE = "sensitive"

# The run cannot work without these. Anything else in 'columns:' is optional:
# leave it out (or set it to null) when the source does not have it.
RECORD_COLUMNS_REQUIRED = (
    UNIQUE_NO,
    SCIENTIFIC_NAME,
    COMMON_NAME,
    SPECIES_NO,
    RECORD_TYPE,
    VERIFIED,
    EASTING,
    NORTHING,
    DATE_OF_RECORD,
    MODIFIED_DATE,
)


# --- Species dictionary ------------------------------------------------------

NBN_NUMBER = "nbn_number"
TAXON_GROUP = "taxon_group"

DICTIONARY_COLUMNS_REQUIRED = (
    SCIENTIFIC_NAME,
    SPECIES_NO,
    NBN_NUMBER,
    COMMON_NAME,
    TAXON_GROUP,
)


# --- Sensitive-species list --------------------------------------------------

SENSITIVE_SPECIES_COLUMNS_REQUIRED = (
    SPECIES_NO,
    NBN_NUMBER,
)


class ColumnMappingError(ValueError):
    """safety.yaml's column mapping does not match the data it describes."""


def column_map(section: str) -> dict:
    """
    The {pipeline name: source column} mapping from one safety.yaml section,
    without the roles set to null (null means "this source does not have it").
    """
    mapping = CONFIG.get(section) or {}
    return {role: column for role, column in mapping.items() if column}


def source_column(role: str, section: str = "columns") -> str:
    """
    BRERC's name for one role, for the rare code that must talk to BRERC's
    data before translation — the incremental SQL filter, for example.
    """
    try:
        return column_map(section)[role]
    except KeyError:
        raise ColumnMappingError(
            f"safety.yaml has no '{section}: {role}' mapping."
        ) from None


def has_role(role: str, section: str = "columns") -> bool:
    """True when safety.yaml maps this role, i.e. the source has the column."""
    return role in column_map(section)


def to_pipeline_names(
    df: pd.DataFrame,
    section: str,
    required: tuple = (),
    what: str = "the source",
) -> pd.DataFrame:
    """
    Translates BRERC's column names into the pipeline's, using one
    safety.yaml section, and keeps ONLY the mapped columns.

    Fails loudly, naming the safety.yaml line to fix, when:
      - a required role is not mapped at all, or
      - a mapped column is not in the data (renamed or dropped upstream).

    Every column that is not mapped — place, comments, recorder details — is
    dropped here, so nothing downstream can publish it by accident.

    Expects column names already cleaned (lowercased, spaces as underscores);
    safety.yaml's right-hand side is matched the same way.
    """
    mapping = {
        role: str(column).strip().lower().replace(" ", "_")
        for role, column in column_map(section).items()
    }

    unmapped = [role for role in required if role not in mapping]
    if unmapped:
        raise ColumnMappingError(
            f"safety.yaml '{section}:' must map {', '.join(unmapped)} "
            f"to a column in {what}."
        )

    absent = {
        role: column for role, column in mapping.items() if column not in df.columns
    }
    if absent:
        lines = "; ".join(
            f"'{section}: {role}' is '{column}'" for role, column in absent.items()
        )
        raise ColumnMappingError(
            f"safety.yaml maps columns that are not in {what}: {lines}. "
            f"Check the right-hand side against the real column names in {what}."
        )

    return df[list(mapping.values())].rename(
        columns={column: role for role, column in mapping.items()}
    )
