import pandas as pd

def normalise_species_name(
    names: pd.Series
) -> pd.Series:

    return (
        names
        .astype("string")
        .str.strip()
        .str.lower()
        .str.replace(
            r"\s+",
            " ",
            regex=True
        )
    )

def resolve_species_numbers(
    records_df: pd.DataFrame,
    dictionary_df: pd.DataFrame
) -> pd.DataFrame:

    records_df = records_df.copy()
    dictionary_df = dictionary_df.copy()

    # Create normalised matching key for records
    records_df["scientific_name_key"] = (
        normalise_species_name(
            records_df["scientific_name"]
        )
    )

    # Create normalised matching key for dictionary
    dictionary_df["scientific_key"] = (
        normalise_species_name(
            dictionary_df["scientific"]
        )
    )

    key_counts = dictionary_df["scientific_key"].value_counts()
    ambiguous_keys = key_counts[key_counts > 1]

    if len(ambiguous_keys) > 0:
        ambiguous_rows = dictionary_df[
            dictionary_df["scientific_key"].isin(ambiguous_keys.index)
        ][["scientific", "scientific_key", "species_no", "nbn_number"]]

        print(
            f"WARNING: {len(ambiguous_keys)} scientific_key collisions "
            f"in dictionary_df - {len(ambiguous_rows)} rows affected. "
            f"drop_duplicates will arbitrarily pick one per key:"
        )
        print(ambiguous_rows.sort_values("scientific_key"))
        # Decide deliberately how to resolve these, e.g. prefer the row
        # where species_no/nbn_number agree with a trusted accepted-name
        # flag, rather than letting drop_duplicates pick row order.

    # Create smaller lookup table
    species_lookup = (
        dictionary_df[
            [
                "scientific",
                "scientific_key",
                "species_no",
                "nbn_number",
                "common_nam",
                "taxanb",
            ]
        ]
        .drop_duplicates(
            subset="scientific_key"
        )
    )

    # Match record species against dictionary
    records_df = records_df.merge(
        species_lookup,
        left_on="scientific_name_key",
        right_on="scientific_key",
        how="left",
        suffixes=("", "_dict")
    )

    # Fail-closed flag
    records_df["species_unresolved"] = (
        records_df["species_no"].isna()
    )

    # --- NEW: D4 "measure match coverage on the full data" ---
    total = len(records_df)
    unresolved = records_df["species_unresolved"].sum()
    coverage = 1 - (unresolved / total) if total else float("nan")

    print(
        f"Species resolution coverage: {coverage:.2%} "
        f"({total - unresolved}/{total} resolved, "
        f"{unresolved} unresolved -> blurred fail-closed)"
    )

    return records_df