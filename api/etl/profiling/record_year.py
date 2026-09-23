"""
Derives the year each occurrence record was made, in one place, so the map
cells, the species index and occurrence_public always agree on it.
"""

import logging

import pandas as pd

import etl.columns as C

logger = logging.getLogger(__name__)

# Optional: the source's own year for the record, used when the free-text date
# cannot be read. None when safety.yaml does not map source_year.
SOURCE_YEAR_COLUMN = C.SOURCE_YEAR if C.has_role(C.SOURCE_YEAR) else None


def derive_record_year(
    df: pd.DataFrame,
    date_column: str,
    source_year_column: str | None = SOURCE_YEAR_COLUMN,
    log: bool = False,
) -> pd.Series:
    """
    Returns each record's year as a nullable integer (Int64).

    1. The record date, when it can be read. Dates arrive in two shapes:
       CSV mode      free text, sometimes with junk prefixed ("  - 17/10/2023"),
                     in UK day-first order;
       database mode a real DATE column, which pandas renders ISO ("2024-05-14").
    2. Otherwise the source's own year column (source_year in safety.yaml).
       Vague dates ("February 2007", "2002", "1985-1990") land here. For a
       range, BRERC's year is the END year — see PUBLICATION_DECISIONS.md.
    3. Otherwise <NA>. Callers decide whether to drop those records.
    """
    raw_dates = df[date_column]

    extracted = raw_dates.astype("string").str.extract(
        r"(\d{1,2}/\d{1,2}/\d{2,4})", expand=False
    )
    day_first = pd.to_datetime(extracted, dayfirst=True, errors="coerce")

    # Anything the regex could not see — real dates, ISO strings — parsed directly.
    direct = pd.to_datetime(raw_dates, dayfirst=True, errors="coerce")

    from_date = day_first.fillna(direct).dt.year.astype("Int64")

    if source_year_column and source_year_column in df.columns:
        from_source = (
            pd.to_numeric(df[source_year_column], errors="coerce")
            .round()
            .astype("Int64")
        )
    else:
        from_source = pd.Series(pd.NA, index=df.index, dtype="Int64")

    year = from_date.fillna(from_source)

    if log:
        logger.info(
            "Record year: %d from date, %d from %s, %d missing",
            from_date.notna().sum(),
            (from_date.isna() & from_source.notna()).sum(),
            source_year_column or "source_year (not configured)",
            year.isna().sum(),
        )

    return year
