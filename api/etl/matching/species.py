"""
Normalises species names and resolves occurrence records against 
the species dictionary, flagging unresolved or malformed entries as fail-closed.
"""

import pandas as pd


def normalise_species_name(names: pd.Series) -> pd.Series:
    """
    Standardise species name strings by stripping whitespace, 
    lowering case, and collapsing spaces.
    """
    return (
        names.astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
    )


def resolve_species_numbers(
    records_df: pd.DataFrame, dictionary_df: pd.DataFrame
) -> pd.DataFrame:
    """
    Matches occurrence records against the species dictionary using normalised names,
    checks for dictionary collisions, validates species number formats, and 
    computes resolution match coverage.
    """
    records_df = records_df.copy()
    dictionary_df = dictionary_df.copy()

    # This function is called twice in a full run — once in pipeline.py and again
    # inside reconcile.py's make_safe_for_publishing — so it has to tolerate being
    # handed data it has already resolved. The first pass leaves the merge's
    # dictionary-side columns behind, and without clearing them the second pass
    # dies with:
    #     MergeError: Passing 'suffixes' which cause duplicate columns
    #     {'species_no_dict', 'nbn_number_dict'} is not allowed
    #
    # Dropping them makes the second pass recompute the same answer rather than
    # fail, so behaviour is unchanged. The second call is arguably redundant and
    # could be removed instead — that is a change to reconciliation's assumptions
    # about its input, so it is left alone here.
    leftovers = [c for c in records_df.columns if c.endswith("_dict")]
    if leftovers:
        records_df = records_df.drop(columns=leftovers)

    # Create normalised matching key for records
    records_df["scientific_name_key"] = normalise_species_name(
        records_df["scientific_name"]
    )

    # Create normalised matching key for dictionary
    dictionary_df["scientific_key"] = normalise_species_name(
        dictionary_df["scientific"]
    )

    # Check for duplicate scientific names in the dictionary
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

    # Create smaller lookup table.
    #
    # BRERC's dictionary calls the common-name column COMMON_NAM — truncated to
    # ten characters, the signature of a DBF/shapefile export. Everything
    # downstream (aggregation/species_index.py, the species table, the API) uses
    # the full name, so rename it here, at the one point where the dictionary is
    # read. Without this the run dies later with:
    #     KeyError: "Missing columns required for species index: ['common_name']"
    species_lookup = dictionary_df[
        [
            "scientific",
            "scientific_key",
            "species_no",
            "nbn_number",
            "common_nam",
            "taxanb",
        ]
    ].drop_duplicates(subset="scientific_key").rename(
        columns={"common_nam": "common_name"}
    )

    # Match record species against dictionary
    records_df = records_df.merge(
        species_lookup,
        left_on="scientific_name_key",
        right_on="scientific_key",
        how="left",
        suffixes=("", "_dict"),
    )

    # Initial fail-closed flag: mark records with missing species numbers as unresolved
    records_df["species_unresolved"] = records_df["species_no"].isna()

    # ...and mark records whose species is not in the dictionary AT ALL.
    #
    # A left join leaves scientific_key null where nothing matched. Without this
    # check, a record carrying a well-formed but unknown species number (say
    # "404404") counted as resolved: it is not missing, and it passes the format
    # test below, so nothing flagged it. It then kept full 100 m precision.
    #
    # That is the fail-OPEN direction, and it is the case that matters most: if
    # we cannot identify the species, we cannot know whether it is protected, so
    # the only safe assumption is that it might be. Being wrong here means
    # publishing a precise location for a sensitive species.
    #
    # BRERC's dictionary is the master list (96,824 species), so an unmatched
    # species number means a typo, a retired code, or a species newer than our
    # copy of the dictionary — all of which warrant caution rather than trust.
    records_df["species_unresolved"] = (
        records_df["species_unresolved"] | records_df["scientific_key"].isna()
    )

    # Clean up trailing decimals from species numbers if they were read as floats
    species_no_string = (
        records_df["species_no"]
        .astype("string")
        .str.replace(
            r"\.0$",
            "",
            regex=True,
        )
    )

    # Validate species number format: must be either plain digits (e.g. 6973)
    # or masked sensitive IDs prefixed with 'BRERC' (e.g. BRERCXXXX)
    valid_species_no = species_no_string.str.match(r"^(BRERC)?\d+$")

    # Flag anything that isn't a valid format as unresolved (fail-closed path)
    non_numeric_species_no = records_df["species_no"].notna() & ~valid_species_no

    records_df["species_unresolved"] = (
        records_df["species_unresolved"] | non_numeric_species_no
    )

    # Measure and print match coverage on the full dataset
    total = len(records_df)
    unresolved = records_df["species_unresolved"].sum()
    coverage = 1 - (unresolved / total) if total else float("nan")

    print(
        f"Species resolution coverage: {coverage:.2%} "
        f"({total - unresolved}/{total} resolved, "
        f"{unresolved} unresolved -> blurred fail-closed)"
    )

    return records_df
