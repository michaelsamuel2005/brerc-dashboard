"""Aggregate generalised records into the public map and summary payloads.

THE RESOLUTION PROBLEM THIS SOLVES
----------------------------------
The map's distribution layer is drawn as 1 km squares. A sensitive record has
already been generalised to a coarser square - 10 km by default. It cannot be
placed in a 1 km cell without inventing precision the record does not have.

So cells are emitted at MIXED resolutions: ordinary records aggregate to 1 km,
sensitive ones stay in their coarser square. `GridCellSchema` carries
`precisionMetres` per cell and the client derives each polygon from the cell id,
so a 10 km cell draws as a 10 km square. This is the NBN/GBIF presentation and it
is honest: a large square says "somewhere in here", which is exactly true.

The alternative - dropping coarse records from the map - would reintroduce the
silent data loss that `sensitivity.py` exists to prevent.

NOTE FOR THE FRONTEND: the current fixtures hardcode `precisionMetres: 1000` for
every cell, so the map has only ever rendered one square size. Mixed resolutions
are valid under the contract but are new behaviour and need a visual check.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .contract import PublicCell, PublicRecord
from .gridref import coarsen, is_public_resolution, precision_metres

#: Development/helper default. The production pipeline always passes the
#: approval-bound PublicationPolicy.map_cell_resolution_metres explicitly.
MAP_CELL_METRES = 1000

#: Development/helper default for the minimum records in a publishable cohort.
#: Production always takes the approval-bound value from PublicationPolicy.
#:
#: Suppression applies to every otherwise-publishable record, ordinary or
#: sensitive. Its cohort is species + year + map cell + precision, and the
#: pipeline removes a suppressed cohort consistently from the map, accessible
#: cell table, individual rows (when enabled), year series and totals. A value of
#: 1 means BRERC explicitly chose no sparse-cohort suppression.
MIN_RECORDS_PER_CELL = 1


@dataclass(frozen=True)
class AggregationReport:
    """What happened, so a run can be audited rather than trusted."""

    cells: tuple[PublicCell, ...]
    records_in: int
    records_aggregated: int
    records_skipped_unpublishable: int
    cells_suppressed_low_count: int
    resolutions_emitted: tuple[int, ...]

    @property
    def suppressed_or_skipped(self) -> int:
        return self.records_skipped_unpublishable


def cell_for(
    record: PublicRecord,
    *,
    map_cell_metres: int = MAP_CELL_METRES,
) -> tuple[str, int] | None:
    """The map cell a record belongs to, or None if it cannot be placed.

    A record finer than the map resolution is coarsened up to it. A record
    already coarser keeps its own square - never coarsened down, never
    artificially sharpened.
    """
    if not is_public_resolution(map_cell_metres):
        raise ValueError(f"map_cell_metres={map_cell_metres!r} is not a public resolution")
    own = precision_metres(record.grid_ref)
    if own is None:
        return None
    target = max(map_cell_metres, own)
    cell_id = coarsen(record.grid_ref, target)
    if cell_id is None:
        return None
    resolved = precision_metres(cell_id)
    if resolved is None or not is_public_resolution(resolved):
        return None
    # The client re-derives precision from the id; they must agree exactly or
    # GridCellSchema rejects the payload.
    if resolved != target:
        return None
    return (cell_id, resolved)


def build_cells(
    records: list[PublicRecord],
    min_records: int = MIN_RECORDS_PER_CELL,
    *,
    map_cell_metres: int = MAP_CELL_METRES,
) -> AggregationReport:
    """Aggregate records into map cells, with an auditable report."""
    if min_records < 1:
        raise ValueError("min_records must be at least 1")
    if not is_public_resolution(map_cell_metres):
        raise ValueError(f"map_cell_metres={map_cell_metres!r} is not a public resolution")

    totals: dict[tuple[str, int, str, int], int] = defaultdict(int)
    verified: dict[tuple[str, int, str, int], int] = defaultdict(int)
    skipped = 0

    for rec in records:
        spatial_key = cell_for(rec, map_cell_metres=map_cell_metres)
        if spatial_key is None:
            skipped += 1
            continue
        key = (rec.species_id, rec.year, *spatial_key)
        totals[key] += 1
        if rec.verified == "accepted":
            verified[key] += 1

    suppressed = 0
    cells: list[PublicCell] = []
    for (species_id, year, cell_id, metres), count in sorted(totals.items()):
        if count < min_records:
            suppressed += 1
            continue
        cells.append(
            PublicCell(
                species_id=species_id,
                year=year,
                cell_id=cell_id,
                precision_metres=metres,
                record_count=count,
                verified_count=verified[(species_id, year, cell_id, metres)],
            )
        )

    return AggregationReport(
        cells=tuple(cells),
        records_in=len(records),
        records_aggregated=sum(c.record_count for c in cells),
        records_skipped_unpublishable=skipped,
        cells_suppressed_low_count=suppressed,
        resolutions_emitted=tuple(sorted({c.precision_metres for c in cells})),
    )


def records_by_year(records: list[PublicRecord]) -> list[dict[str, int]]:
    """One species' records-by-year series, ascending.

    A combined series is not a valid species response. Requiring one internal
    species key prevents totals from different taxa being blended silently.
    """
    _require_single_species(records)
    counts: dict[int, int] = defaultdict(int)
    for rec in records:
        counts[rec.year] += 1
    return [{"year": y, "count": counts[y]} for y in sorted(counts)]


def records_by_year_by_species(
    records: list[PublicRecord],
) -> dict[str, list[dict[str, int]]]:
    """All species' year rows, suitable for a future public DB load."""
    grouped: dict[str, list[PublicRecord]] = defaultdict(list)
    for record in records:
        grouped[record.species_id].append(record)
    return {species_id: records_by_year(grouped[species_id]) for species_id in sorted(grouped)}


def year_range(records: list[PublicRecord]) -> tuple[int, int] | None:
    """One species' (min, max) year, or None when there are no records."""
    _require_single_species(records)
    years = [r.year for r in records]
    if not years:
        return None
    return (min(years), max(years))


def _require_single_species(records: list[PublicRecord]) -> str | None:
    species_ids = {record.species_id for record in records}
    if len(species_ids) > 1:
        raise ValueError(
            "species-scoped aggregation received multiple species; select one "
            "species or use the by-species aggregation"
        )
    return next(iter(species_ids), None)


def reconciles(report: AggregationReport, records: list[PublicRecord]) -> bool:
    """EXACT: every record is either aggregated or skipped as unpublishable.

    Deliberately `==`, not `<=`. An inequality passes when records disappear,
    which is precisely the failure this check exists to catch. Suppression is
    applied upstream in `pipeline.run_pipeline`, so by the time cells are built
    there is nothing left to suppress and the two terms must sum exactly.
    """
    accounted = report.records_aggregated + report.records_skipped_unpublishable
    return accounted == len(records) and report.records_in == len(records)
