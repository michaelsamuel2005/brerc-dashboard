"""
Classifies occurrence records for sensitivity by evaluating species lists, 
unresolved entries, record types, and source flags, and assigns appropriate 
spatial blurring resolutions.
"""

import pandas as pd

from etl.safety_gate.rules import (
    DEFAULT_SENSITIVE_RESOLUTION_M,
    FLAGGED_RECORD_TYPES,
    load_sensitive_species,
    D0_FLOOR_M,
)


def classify_chunk(
    df: pd.DataFrame,
    *,
    source_provides_sensitivity: bool | None = None,
) -> pd.DataFrame:
    """
    Evaluates records against multi-factor sensitivity rules,
    tracks specific sensitivity reasons per row, and assigns
    blur resolution requirements.

    source_provides_sensitivity:
        Whether this source is expected to carry a "sensitive" column.

        None (the default) means "work it out, and refuse if it is ambiguous".
        Pass False for a source that genuinely has no sensitivity flag — a CSV
        extract, for example. That is a statement about the source, and it
        belongs where the source is configured rather than being assumed here.
    """
    df = df.copy()

    sensitive_species_nos, _ = load_sensitive_species()

    # Required columns for classification to run
    required_columns = {
        "species_no",
        "species_unresolved",
        "record_type",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"classify_chunk() missing required columns: {sorted(missing)}"
        )

    # Setting up the masks:

    # Unresolved species: True for records whose species can't be resolved.
    unresolved_mask = df["species_unresolved"]

    # Sensitive species: True for records belonging to a sensitive species.
    sensitive_species_mask = df["species_no"].isin(sensitive_species_nos)

    # Sensitive Record Type: True for records whose record type is classified as sensitive.
    flagged_record_type_mask = df["record_type"].isin(FLAGGED_RECORD_TYPES)

    # Source sensitivity flag: True for records explicitly marked as sensitive by
    # the source.
    #
    # A missing column used to mean "nothing here is sensitive". That is right for a
    # source which genuinely has no flag, and wrong — silently, and at full precision
    # — for a source which HAS one that was renamed, dropped or misspelled upstream.
    # The two arrive here looking identical, so the caller has to say which it is.
    has_sensitivity_column = "sensitive" in df.columns

    if source_provides_sensitivity is None and not has_sensitivity_column:
        raise ValueError(
            "classify_chunk(): no 'sensitive' column in this chunk. If this source "
            "genuinely has no sensitivity flag, pass source_provides_sensitivity=False "
            "at the call site. Defaulting to 'not sensitive' cannot tell that apart "
            "from a column that was renamed or dropped upstream, and would publish "
            "every affected record at full precision."
        )

    if source_provides_sensitivity and not has_sensitivity_column:
        raise ValueError(
            "classify_chunk(): this source is declared to provide 'sensitive', but "
            "the column is absent. Refusing rather than treating every record as "
            "not sensitive."
        )

    if has_sensitivity_column:
        sensitive_source_mask = (
            df["sensitive"]
            .astype("string")
            .str.strip()
            .str.lower()
            .isin(["yes", "true", "1"])
        )
    else:
        sensitive_source_mask = pd.Series(
            False,
            index=df.index,
        )

    # Combining the masks: If row is TRUE in any of the above masks,
    # it's considered sensitive.
    sensitive_mask = (
        unresolved_mask
        | sensitive_species_mask
        | flagged_record_type_mask
        | sensitive_source_mask
    )

    # Mark general sensitivity and blurring requirement flags
    df["is_sensitive"] = sensitive_mask
    df["blurred"] = sensitive_mask

    # Initialize tracking lists for why a record was classified as sensitive
    # Start with an empty list for every record.
    df["sensitivity_reason"] = [[] for _ in range(len(df))]

    # Add "unresolved_species" to records where the species could not be resolved.
    df.loc[unresolved_mask, "sensitivity_reason"] = df.loc[
        unresolved_mask, "sensitivity_reason"
    ].apply(lambda x: x + ["unresolved_species"])

    # Add "sensitive_record_type" to records with a flagged record type.
    df.loc[flagged_record_type_mask, "sensitivity_reason"] = df.loc[
        flagged_record_type_mask, "sensitivity_reason"
    ].apply(lambda x: x + ["sensitive_record_type"])

    # Add "sensitive_species" to records containing a sensitive species.
    df.loc[sensitive_species_mask, "sensitivity_reason"] = df.loc[
        sensitive_species_mask, "sensitivity_reason"
    ].apply(lambda x: x + ["sensitive_species"])

    # Add "source_sensitive" to records explicitly marked as sensitive
    # by the source/view.
    df.loc[sensitive_source_mask, "sensitivity_reason"] = df.loc[
        sensitive_source_mask, "sensitivity_reason"
    ].apply(lambda x: x + ["source_sensitive"])

    # Convert empty lists into "not_sensitive" for records that triggered no rules.
    df.loc[df["sensitivity_reason"].apply(len) == 0, "sensitivity_reason"] = (
        "not_sensitive"
    )

    # Assign default minimum (D0) spatial resolution to all records
    df["resolution_m"] = D0_FLOOR_M

    # Increase blur resolution distance for flagged sensitive records
    df.loc[sensitive_mask, "resolution_m"] = DEFAULT_SENSITIVE_RESOLUTION_M

    return df
