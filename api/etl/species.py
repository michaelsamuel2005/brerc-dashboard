"""Resolve a scientific name to a BRERC species number and its sensitivity.

WHY THIS IS ARCHITECTURALLY REQUIRED
------------------------------------
The older BRERC spreadsheet exports carry NO species-id column. Both client
samples have only `Scientific_Name` and `Common_Name`:

    Scientific_Name, Common_Name, Grid_Ref, Place, Date_of_Record, Abundance,
    Sex_Stage, Record_Type, Precise_Date, Vague_Date, vitality, verified,
    YearEnd, Comments, Source, unique_No, licence, Eastings, Northings

The sensitivity flag lives in the species dictionary, keyed on `SPECIES_NO`. For
those exports the gate cannot run on an occurrence row alone, so the dictionary
provides the missing id. Measured on the client samples, that join resolves
998/998 and 918/918 rows (100%), and all 547 and 6 distinct names.

The live `dashboard.main_data_dash` view is different: it supplies `species_no`
itself. That mapped source id is authoritative. The dictionary may verify that
the scientific name identifies the same id and contribute sensitivity metadata,
but it must never replace the live id. Conflicting or ambiguous joins are
withheld by `pipeline.py`.

FAIL-CLOSED
-----------
A name that does not resolve yields `None`, and `sensitivity.is_sensitive(None)`
treats it as sensitive. An unrecognised taxon is exactly the case where we must
not assume it is safe to publish precisely.

SPECIES NUMBERS ARE STRINGS
---------------------------
63% of dictionary entries are alphanumeric ("BRERC10469", "6973a", "Z5567"), so
ids are carried and compared as normalised strings throughout.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .sensitivity import normalise_species_id


def normalise_name(name: object) -> str:
    """Normalisation used for dictionary lookup: casefolded, whitespace-collapsed."""
    return " ".join(str(name).strip().lower().split())


@dataclass(frozen=True)
class SpeciesRecord:
    species_no: str
    scientific_name: str
    common_name: str | None
    sensitive: bool


class SpeciesDictionary:
    """Name -> species number, built from the BRERC species dictionary export."""

    def __init__(self, entries: Iterable[SpeciesRecord]) -> None:
        self._by_name: dict[str, SpeciesRecord] = {}
        self._duplicates: list[str] = []
        self._ambiguous: set[str] = set()
        for entry in entries:
            key = normalise_name(entry.scientific_name)
            species_no = normalise_species_id(entry.species_no)
            if not key or species_no is None:
                continue
            normalised = SpeciesRecord(
                species_no=species_no,
                scientific_name=str(entry.scientific_name).strip(),
                common_name=entry.common_name,
                sensitive=entry.sensitive,
            )
            existing = self._by_name.get(key)
            if existing is not None:
                self._duplicates.append(key)
                if existing.species_no != normalised.species_no:
                    # One scientific name identifying two taxa is not a usable
                    # join. Retain the first record only for diagnostics, mark
                    # the key ambiguous, and make every public lookup fail.
                    self._ambiguous.add(key)
                elif normalised.sensitive and not existing.sensitive:
                    # Identical duplicate ids are not identity-ambiguous, but a
                    # sensitivity disagreement must fail safe in the direction
                    # of protection.
                    self._by_name[key] = SpeciesRecord(
                        species_no=existing.species_no,
                        scientific_name=existing.scientific_name,
                        common_name=existing.common_name or normalised.common_name,
                        sensitive=True,
                    )
                continue
            self._by_name[key] = normalised

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def duplicate_names(self) -> tuple[str, ...]:
        """Scientific names appearing more than once. Should normally be empty."""
        return tuple(sorted(set(self._duplicates)))

    @property
    def ambiguous_names(self) -> tuple[str, ...]:
        """Names mapped to more than one species number.

        These names are deliberately unavailable to ``lookup``: choosing the
        first dictionary row would make input order determine which taxon (and
        therefore which sensitivity rule) is applied.
        """
        return tuple(sorted(self._ambiguous))

    @property
    def sensitive_count(self) -> int:
        return sum(1 for e in self._by_name.values() if e.sensitive)

    def digest(self) -> str:
        """Deterministic digest of identity and sensitivity inputs used by the gate."""
        document = {
            "entries": [
                {
                    "name": name,
                    "speciesNo": entry.species_no,
                    "sensitive": entry.sensitive,
                }
                for name, entry in sorted(self._by_name.items())
            ],
            "ambiguousNames": sorted(self._ambiguous),
        }
        canonical = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def lookup(self, scientific_name: object) -> SpeciesRecord | None:
        key = normalise_name(scientific_name)
        if key in self._ambiguous:
            return None
        return self._by_name.get(key)

    def is_ambiguous(self, scientific_name: object) -> bool:
        """Whether a name maps to conflicting species numbers."""
        return normalise_name(scientific_name) in self._ambiguous

    def species_id_for(self, scientific_name: object) -> str | None:
        """The species number for a name, or None when it does not resolve.

        None propagates to `sensitivity.is_sensitive`, which fails closed.
        """
        found = self.lookup(scientific_name)
        return found.species_no if found else None

    def coverage(self, names: Iterable[object]) -> tuple[int, int, list[str]]:
        """(resolved, total, unresolved_names) for a batch - use before a run."""
        unresolved: list[str] = []
        total = 0
        for name in names:
            total += 1
            if self.lookup(name) is None:
                unresolved.append(str(name))
        return (total - len(unresolved), total, unresolved)

    @classmethod
    def from_rows(
        cls,
        rows: Iterable[dict[str, object]],
        *,
        id_column: str = "SPECIES_NO",
        name_column: str = "SCIENTIFIC",
        common_column: str = "COMMON_NAM",
        sensitive_column: str = "SENSITIVE",
    ) -> SpeciesDictionary:
        """Build from dictionary rows. Column names default to the export's own."""
        entries: list[SpeciesRecord] = []
        for row in rows:
            species_no = normalise_species_id(row.get(id_column))
            name = row.get(name_column)
            if species_no is None or not str(name).strip():
                continue
            raw_sensitive = row.get(sensitive_column)
            sensitive = (
                raw_sensitive is not None
                and str(raw_sensitive).strip() != ""
                and str(raw_sensitive).strip().lower() not in {"nan", "no", "n", "false", "0"}
            )
            common = str(row.get(common_column) or "").strip() or None
            entries.append(SpeciesRecord(species_no, str(name).strip(), common, sensitive))
        return cls(entries)

    @classmethod
    def from_csv(cls, path: str | Path, **kwargs: str) -> SpeciesDictionary:
        with Path(path).open(newline="", encoding="utf-8-sig") as handle:
            return cls.from_rows([dict(r) for r in csv.DictReader(handle)], **kwargs)
