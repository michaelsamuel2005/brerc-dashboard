"""
Loads a BRERC .xls export (and optionally a species dictionary CSV) into the
mock brerc_source database created by 01_brerc_source.sql.

Usage (from the api folder, with the venv active):

    pip install xlrd            # only extra dependency: reads the old .xls format
    python scripts/local_db/load_source_data.py "C:\\path\\to\\sampleversion 4.xls"
    python scripts/local_db/load_source_data.py export.xls --dictionary ..\\data\\full_dictionary.csv

Connection: --url, else SOURCE_DATABASE_URL (from api/.env), e.g.
    postgresql://postgres:YOUR_PASSWORD@localhost:5432/brerc_source

Replaces the contents of brerc_source.occurrences_raw and
brerc_source.species_dictionary on every run.

Without --dictionary, the dictionary is derived from the export itself
(one row per Species_No). That makes species matching 100% by construction,
so use BRERC's real dictionary when you have it.
"""

import argparse
import io
import os
import sys
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv

RAW_COLUMNS = [
    "scientific_name", "common_name", "grid_ref", "place", "date_of_record",
    "abundance", "sex_stage", "record_type", "startdate", "species_no",
    "precise_date", "vague_date", "vitality", "digital_or_paper",
    "date_entered", "bnes", "bcc", "sglos", "nsom", "yearend", "yearstart",
    "enddate", "comments", "source", "bliss", "taxabrerc", "unique_no",
    "licence", "sensitive", "taxonid", "easting", "northing", "taxanb",
    "brercstatus", "national_status", "legalprotect", "bap", "rspb_list",
    "brercnotable", "datemdbmodified", "verified", "eastings", "northings",
]
DATE_COLUMNS = ["startdate", "precise_date", "enddate", "date_entered", "datemdbmodified"]
INT_COLUMNS = ["yearend", "yearstart", "unique_no", "easting", "northing", "eastings", "northings"]
DICTIONARY_COLUMNS = ["species_no", "scientific", "common_nam", "nbn_number", "taxanb"]


def clean_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    return df


def as_id_text(series: pd.Series) -> pd.Series:
    """Species numbers as text, without a trailing .0 if Excel stored them as floats."""
    return series.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)


def read_export(path: Path) -> pd.DataFrame:
    df = clean_names(pd.read_excel(path, engine="xlrd", dtype=object))

    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        sys.exit(f"The export is missing expected columns: {missing}")
    extra = [c for c in df.columns if c not in RAW_COLUMNS]
    if extra:
        print(f"Ignoring columns not in occurrences_raw: {extra}")

    df = df[RAW_COLUMNS]
    for column in DATE_COLUMNS:
        df[column] = pd.to_datetime(df[column], errors="coerce", dayfirst=True).dt.date
    for column in INT_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce").round().astype("Int64")
    df["species_no"] = as_id_text(df["species_no"])

    if df["unique_no"].isna().any():
        sys.exit(f"{df['unique_no'].isna().sum()} rows have no unique_No.")
    duplicates = df["unique_no"].duplicated().sum()
    if duplicates:
        sys.exit(f"{duplicates} duplicate unique_No values; unique_no is the primary key.")
    return df


def read_dictionary(path: Path | None, export: pd.DataFrame) -> pd.DataFrame:
    if path is None:
        print("No --dictionary given: deriving one from the export (1 row per species_no).")
        dictionary = export.drop_duplicates("species_no").rename(
            columns={
                "scientific_name": "scientific",
                "common_name": "common_nam",
                "taxonid": "nbn_number",
            }
        )
    else:
        dictionary = clean_names(pd.read_csv(path, dtype=str))

    missing = [c for c in DICTIONARY_COLUMNS if c not in dictionary.columns]
    if missing:
        sys.exit(f"The dictionary is missing columns: {missing}")

    dictionary = dictionary[DICTIONARY_COLUMNS].copy()
    dictionary["species_no"] = as_id_text(dictionary["species_no"])
    dictionary = dictionary.dropna(subset=["species_no", "scientific"])
    dictionary = dictionary.drop_duplicates("species_no")
    return dictionary


def copy_into(cursor, table: str, df: pd.DataFrame) -> None:
    buffer = io.StringIO()
    df.astype(object).where(pd.notna(df), None).to_csv(buffer, index=False, header=False)
    columns = ", ".join(df.columns)
    with cursor.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
        copy.write(buffer.getvalue())


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="BRERC .xls export")
    parser.add_argument("--dictionary", type=Path, help="species dictionary CSV (optional)")
    parser.add_argument("--url", default=os.getenv("SOURCE_DATABASE_URL"), help="brerc_source connection URL")
    args = parser.parse_args()

    if not args.url:
        sys.exit("No connection: pass --url or set SOURCE_DATABASE_URL in api/.env.")

    export = read_export(args.export)
    dictionary = read_dictionary(args.dictionary, export)

    with psycopg.connect(args.url) as connection, connection.cursor() as cursor:
        cursor.execute("TRUNCATE brerc_source.occurrences_raw, brerc_source.species_dictionary")
        copy_into(cursor, "brerc_source.occurrences_raw", export)
        copy_into(cursor, "brerc_source.species_dictionary", dictionary)
        connection.commit()

        cursor.execute("SELECT count(*) FROM brerc_source.vw_occurrences")
        occurrences = cursor.fetchone()[0]
        cursor.execute("SELECT count(*) FROM brerc_source.vw_species_dictionary")
        species = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT count(*) FROM brerc_source.vw_occurrences o
            WHERE NOT EXISTS (
                SELECT 1 FROM brerc_source.vw_species_dictionary d
                WHERE lower(trim(d.scientific)) = lower(trim(o.scientific_name))
            )
            """
        )
        unmatched = cursor.fetchone()[0]

    print(f"Loaded {occurrences} occurrence records and {species} dictionary species.")
    print(f"{unmatched} records have a scientific name not in the dictionary "
          "(the ETL will blur these to 1 km).")


if __name__ == "__main__":
    main()
