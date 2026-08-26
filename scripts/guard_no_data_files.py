#!/usr/bin/env python3
"""Fail if a data file is tracked by git.

WHY
---
The subset BRERC supplied is REAL CLIENT DATA: precise grid references, place
names, recorder attributions and free-text comments carrying `per`/`det.`/`by`
determiner names. `Data_Governance_and_Compliance.md` is unambiguous - it must
never be committed.

`.gitignore` is necessary but not sufficient. `git add -f`, a rename that dodges
a pattern, a spreadsheet dropped into a new directory, an extract saved as
`sample.xlsx` next to the notebook that made it - all defeat it silently, and a
commit that reaches a private remote has still left the controlled system.

So the ignore rules stop the accident and this check catches what slips past.
It reads `git ls-files`, so it sees exactly what is tracked, not what happens to
be on disk.

WHAT IT DOES NOT DO
-------------------
It does not scan history. If something is already committed, ignoring it now
does not remove it - that needs a history rewrite and a rotated data agreement
conversation, not a CI check. This guard's job is to stop the next one.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path, PurePosixPath

#: Extensions that must never be tracked. Tabular, archive, geospatial and
#: database formats - the shapes a records-centre extract actually arrives in.
FORBIDDEN_SUFFIXES: frozenset[str] = frozenset(
    {
        # spreadsheets and delimited text
        ".xls",
        ".xlsx",
        ".xlsm",
        ".xlsb",
        ".ods",
        ".csv",
        ".tsv",
        ".psv",
        # archives, which hide all of the above
        ".zip",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".tar",
        # databases and columnar formats
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mdb",
        ".accdb",
        ".parquet",
        ".feather",
        ".dta",
        ".sav",
        # geospatial
        ".shp",
        ".dbf",
        ".shx",
        ".prj",
        ".gpkg",
        ".geojson",
        ".kml",
        ".kmz",
        ".gpx",
        ".mbtiles",
        ".gdb",
        ".gdbtable",
        ".gdbtablx",
        ".gdbindexes",
        ".gdbtablex",
        # serialised objects, which can carry anything and execute on load
        ".pkl",
        ".pickle",
        ".joblib",
        ".npy",
        ".npz",
    }
)

#: Exact files that are allowed to carry a forbidden suffix, with the reason.
#: Directory-wide exemptions are deliberately unsupported: an exempt fixture
#: directory would also exempt a real client workbook dropped beside a fixture.
#: Add only a reviewed, synthetic file's full repository-relative path.
ALLOWED: dict[str, str] = {
    "db/test/e2e_sensitive_species.csv": (
        "reviewed synthetic two-row taxonomy fixture; contains no occurrences, "
        "locations, people or client extract"
    ),
}

# Git tracks files inside a dataset directory, not the directory entry itself.
FORBIDDEN_DATASET_DIR_SUFFIXES: frozenset[str] = frozenset({".gdb"})

# These are JSON/SQL/PDF by extension, but they carry BRERC's internal view
# definition, infrastructure metadata or named approval evidence. They require
# the same force-add protection as client record extracts.
FORBIDDEN_PATH_ENDINGS: frozenset[str] = frozenset(
    {
        ".brerc-view-capture.json",
        ".brerc-view-definition.sql",
        ".brerc-view-approval.pending.json",
        ".brerc-view-approval.json",
    }
)
FORBIDDEN_EXACT_NAMES: frozenset[str] = frozenset(
    {
        "brerc-postgres db for 180dc-310726-161446.pdf",
        ".pgpass",
        "pgpass.conf",
        ".pg_service.conf",
        "pg_service.conf",
        "brerc-source.pgpass",
        "brerc-source.pg_service.conf",
        "brerc-source-client.key",
        "brerc-source-client.crt",
    }
)
FORBIDDEN_SECRET_SUFFIXES: frozenset[str] = frozenset(
    {".key", ".pgpass", ".pg_service.conf"}
)
FORBIDDEN_EXACT_PATHS: frozenset[str] = frozenset(
    {"api/configuration.yaml", "api/loader.configuration.yaml"}
)

# A renamed binary must not evade the suffix check. Read only a small prefix;
# the guard reports the path, never file contents.
MAGIC_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (0, b"-----BEGIN PRIVATE KEY-----", "PEM private key"),
    (0, b"-----BEGIN ENCRYPTED PRIVATE KEY-----", "encrypted PEM private key"),
    (0, b"-----BEGIN RSA PRIVATE KEY-----", "RSA PEM private key"),
    (0, b"-----BEGIN EC PRIVATE KEY-----", "EC PEM private key"),
    (0, b"-----BEGIN OPENSSH PRIVATE KEY-----", "OpenSSH private key"),
    (0, b"PK\x03\x04", "ZIP/xlsx/ods archive"),
    (0, b"PK\x05\x06", "empty ZIP archive"),
    (0, b"PK\x07\x08", "spanned ZIP archive"),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE compound/xls/mdb file"),
    (0, b"\x1f\x8b", "gzip archive"),
    (0, b"BZh", "bzip2 archive"),
    (0, b"\xfd7zXZ\x00", "xz archive"),
    (0, b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (0, b"Rar!\x1a\x07\x00", "RAR4 archive"),
    (0, b"Rar!\x1a\x07\x01\x00", "RAR5 archive"),
    (0, b"SQLite format 3\x00", "SQLite database"),
    (0, b"\x00\x01\x00\x00Standard Jet DB", "Access MDB database"),
    (0, b"\x00\x01\x00\x00Standard ACE DB", "Access ACCDB database"),
    (0, b"PAR1", "Parquet file"),
    (0, b"ARROW1", "Arrow/Feather v2 file"),
    (0, b"FEA1", "Feather v1 file"),
    (257, b"ustar", "tar archive"),
)

# A renamed delimited extract has no binary signature. Require several exact
# source-column names in one delimited row so ordinary prose and source code do
# not trigger the heuristic.
SOURCE_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "unique_no",
        "species_no",
        "scientific_name",
        "grid_ref",
        "easting",
        "eastings",
        "northing",
        "northings",
        "place",
        "comments",
        "date_of_record",
        "yearend",
        "sensitive",
        "sensitivity",
        "recorders",
        "determiners",
    }
)


def tracked_files(repo_root: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", repo_root, "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [
        raw_path.decode("utf-8", errors="surrogateescape")
        for raw_path in result.stdout.split(b"\0")
        if raw_path
    ]


def is_allowed(path: str) -> str | None:
    """The reason this path is exempt, or None."""
    return ALLOWED.get(path)


def dataset_component(path: str) -> str | None:
    """The forbidden dataset-directory component in path, if any."""
    for part in PurePosixPath(path).parts:
        if PurePosixPath(part).suffix.casefold() in FORBIDDEN_DATASET_DIR_SUFFIXES:
            return part
    return None


def magic_kind(repo_root: str, path: str) -> str | None:
    """The recognised forbidden content type, if the tracked file has one."""
    file_path = Path(repo_root, *PurePosixPath(path).parts)
    if file_path.is_symlink() or not file_path.is_file():
        return None
    with file_path.open("rb") as handle:
        head = handle.read(4096)
    for offset, signature, label in MAGIC_SIGNATURES:
        if head[offset : offset + len(signature)] == signature:
            return label
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines()[:10]:
        for delimiter in (",", "\t", ";", "|"):
            cells = next(csv.reader([line], delimiter=delimiter))
            normalised = {
                cell.strip().casefold().replace(" ", "_").replace("-", "_")
                for cell in cells
            }
            if len(normalised & SOURCE_HEADER_NAMES) >= 3:
                return "delimited source extract"
    return None


def check(repo_root: str) -> list[str]:
    problems: list[str] = []
    for path in tracked_files(repo_root):
        if is_allowed(path):
            continue
        suffix = PurePosixPath(path).suffix.lower()
        lower_path = path.casefold()
        exact_name = PurePosixPath(path).name.casefold()
        if (
            suffix in FORBIDDEN_SUFFIXES
            or lower_path in FORBIDDEN_EXACT_PATHS
            or any(lower_path.endswith(ending) for ending in FORBIDDEN_PATH_ENDINGS)
            or exact_name in FORBIDDEN_EXACT_NAMES
            or any(lower_path.endswith(ending) for ending in FORBIDDEN_SECRET_SUFFIXES)
            or dataset_component(path) is not None
            or magic_kind(repo_root, path) is not None
        ):
            problems.append(path)
    return sorted(problems)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repository root (default: .)")
    args = parser.parse_args()

    try:
        problems = check(args.repo_root)
    except subprocess.CalledProcessError as exc:
        print(f"FAIL: could not list tracked files: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError:
        print("FAIL: git is not available on PATH.", file=sys.stderr)
        return 2

    if problems:
        print(
            "FAIL: client data, connector secrets or controlled attestation file(s) "
            "are tracked by git."
        )
        print()
        for path in problems:
            print(f"  {path}")
        print()
        print(
            "BRERC client data, connector credentials and controlled live-view evidence "
            "must never be committed."
        )
        print("To untrack without deleting your local copy:")
        print()
        for path in problems:
            print(f"  git rm --cached {path!r}")
        print()
        print("Then confirm it is ignored, and tell the project leader if the file")
        print("ever reached a remote - an ignore rule does not undo a push.")
        print()
        print("If a file is genuinely not data (a synthetic fixture, a config file),")
        print("add its path to ALLOWED in this script with the reason.")
        return 1

    print("OK: no data files are tracked by git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
