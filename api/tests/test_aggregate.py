"""Tests for map-cell aggregation, including the mixed-resolution case."""

import unittest

from etl.aggregate import (
    MAP_CELL_METRES,
    build_cells,
    reconciles,
    records_by_year,
    records_by_year_by_species,
    year_range,
)
from etl.contract import PublicRecord
from etl.gridref import precision_metres
from etl.policy import DEVELOPMENT_POLICY
from etl.sensitivity import generalise


def rec(
    grid_ref: str,
    year: int = 2020,
    verified: str = "accepted",
    precision: int | None = None,
    rid: str = "1",
    species_id: str = "5088",
) -> PublicRecord:
    return PublicRecord(
        record_id=rid,
        species_id=species_id,
        scientific_name="Anguis fragilis",
        common_name="Slow-worm",
        grid_ref=grid_ref,
        precision_metres=precision if precision is not None else (precision_metres(grid_ref) or 0),
        place=None,
        year=year,
        abundance=None,
        record_type=None,
        verified=verified,
        source="recorder",
    )


class TestCellAggregation(unittest.TestCase):
    def test_hundred_metre_records_aggregate_into_one_kilometre_cells(self):
        # ST585725 and ST587721 both sit in ST5872.
        report = build_cells([rec("ST585725", rid="a"), rec("ST587721", rid="b")])
        self.assertEqual(len(report.cells), 1)
        self.assertEqual(report.cells[0].cell_id, "ST5872")
        self.assertEqual(report.cells[0].precision_metres, MAP_CELL_METRES)
        self.assertEqual(report.cells[0].record_count, 2)

    def test_records_in_different_squares_stay_separate(self):
        report = build_cells([rec("ST585725", rid="a"), rec("ST597728", rid="b")])
        self.assertEqual({c.cell_id for c in report.cells}, {"ST5872", "ST5972"})

    def test_verified_count_counts_only_accepted(self):
        report = build_cells(
            [
                rec("ST585725", verified="accepted", rid="a"),
                rec("ST585725", verified="unconfirmed", rid="b"),
                rec("ST585725", verified="rejected", rid="c"),
                rec("ST585725", verified="unknown", rid="d"),
            ]
        )
        cell = report.cells[0]
        self.assertEqual(cell.record_count, 4)
        self.assertEqual(cell.verified_count, 1)

    def test_verified_count_never_exceeds_record_count(self):
        # GridCellSchema rejects verifiedCount > recordCount.
        report = build_cells([rec("ST585725", verified="accepted", rid=str(i)) for i in range(5)])
        for cell in report.cells:
            self.assertLessEqual(cell.verified_count, cell.record_count)

    def test_cells_are_sorted_deterministically(self):
        a = build_cells([rec("ST597728", rid="a"), rec("ST585725", rid="b")])
        b = build_cells([rec("ST585725", rid="b"), rec("ST597728", rid="a")])
        self.assertEqual([c.cell_id for c in a.cells], [c.cell_id for c in b.cells])

    def test_empty_input_yields_no_cells(self):
        report = build_cells([])
        self.assertEqual(report.cells, ())
        self.assertEqual(report.records_in, 0)

    def test_different_species_in_the_same_square_are_never_combined(self):
        report = build_cells(
            [
                rec("ST585725", rid="a", species_id="5088"),
                rec("ST585725", rid="b", species_id="999999"),
            ]
        )
        self.assertEqual(len(report.cells), 2)
        self.assertEqual(
            {(cell.species_id, cell.record_count) for cell in report.cells},
            {("5088", 1), ("999999", 1)},
        )


class TestMixedResolution(unittest.TestCase):
    """A sensitive record generalised to 10 km cannot be forced into a 1 km cell."""

    def test_a_ten_kilometre_record_keeps_its_own_square(self):
        report = build_cells([rec("ST57")])
        self.assertEqual(len(report.cells), 1)
        self.assertEqual(report.cells[0].cell_id, "ST57")
        self.assertEqual(report.cells[0].precision_metres, 10000)

    def test_coarse_and_fine_records_produce_cells_at_both_resolutions(self):
        report = build_cells([rec("ST585725", rid="a"), rec("ST57", rid="b")])
        self.assertEqual(report.resolutions_emitted, (1000, 10000))

    def test_a_coarse_record_is_never_placed_in_a_fine_cell(self):
        report = build_cells([rec("ST57")])
        for cell in report.cells:
            self.assertGreaterEqual(cell.precision_metres, 10000)

    def test_end_to_end_a_sensitive_record_lands_in_a_coarse_cell(self):
        gen = generalise(
            "ST5877972166",
            2028,  # sensitive, 1 m input
            policy=DEVELOPMENT_POLICY,
            known=True,
        )
        self.assertTrue(gen.emit)
        report = build_cells([rec(gen.grid_ref)])
        self.assertEqual(
            report.cells[0].precision_metres, DEVELOPMENT_POLICY.default_sensitive_metres
        )
        self.assertGreater(report.cells[0].precision_metres, MAP_CELL_METRES)

    def test_every_emitted_cell_id_resolves_to_its_stated_precision(self):
        # GridCellSchema's superRefine enforces exactly this on the client.
        report = build_cells([rec("ST585725", rid="a"), rec("ST57", rid="b"), rec("ST", rid="c")])
        for cell in report.cells:
            self.assertEqual(precision_metres(cell.cell_id), cell.precision_metres)


class TestUnpublishableRecords(unittest.TestCase):
    def test_an_unparseable_reference_is_skipped_not_crashed(self):
        report = build_cells([rec("not-a-ref", precision=1000), rec("ST585725", rid="b")])
        self.assertEqual(report.records_skipped_unpublishable, 1)
        self.assertEqual(len(report.cells), 1)

    def test_a_tetrad_is_skipped(self):
        report = build_cells([rec("ST57A", precision=2000)])
        self.assertEqual(report.records_skipped_unpublishable, 1)
        self.assertEqual(report.cells, ())

    def test_skipped_records_are_counted_not_hidden(self):
        report = build_cells([rec("junk", precision=1000, rid=str(i)) for i in range(3)])
        self.assertEqual(report.records_in, 3)
        self.assertEqual(report.records_skipped_unpublishable, 3)


class TestSuppression(unittest.TestCase):
    def test_default_publishes_every_occupied_square(self):
        report = build_cells([rec("ST585725")])
        self.assertEqual(len(report.cells), 1)
        self.assertEqual(report.cells_suppressed_low_count, 0)

    def test_a_threshold_hides_sparse_cells_and_counts_them(self):
        report = build_cells(
            [rec("ST585725", rid="a"), rec("ST597728", rid="b"), rec("ST597729", rid="c")],
            min_records=2,
        )
        self.assertEqual([c.cell_id for c in report.cells], ["ST5972"])
        self.assertEqual(report.cells_suppressed_low_count, 1)

    def test_suppressed_records_do_not_appear_in_the_aggregated_total(self):
        report = build_cells(
            [rec("ST585725", rid="a"), rec("ST597728", rid="b"), rec("ST597729", rid="c")],
            min_records=2,
        )
        self.assertEqual(report.records_aggregated, 2)

    def test_a_threshold_below_one_is_rejected(self):
        with self.assertRaises(ValueError):
            build_cells([], min_records=0)


class TestSeriesAndReconciliation(unittest.TestCase):
    def test_records_by_year_is_ascending_and_complete(self):
        series = records_by_year(
            [
                rec("ST5872", year=2020, rid="a"),
                rec("ST5872", year=1999, rid="b"),
                rec("ST5872", year=2020, rid="c"),
            ]
        )
        self.assertEqual(series, [{"year": 1999, "count": 1}, {"year": 2020, "count": 2}])

    def test_records_by_year_totals_match_the_input(self):
        records = [rec("ST5872", year=y, rid=str(i)) for i, y in enumerate([2000, 2000, 2001])]
        self.assertEqual(sum(p["count"] for p in records_by_year(records)), len(records))

    def test_year_range(self):
        self.assertEqual(
            year_range([rec("ST5872", year=1999, rid="a"), rec("ST5872", year=2024, rid="b")]),
            (1999, 2024),
        )
        self.assertIsNone(year_range([]))

    def test_a_species_series_never_combines_different_taxa(self):
        mixed = [
            rec("ST5872", year=2020, rid="a", species_id="5088"),
            rec("ST5872", year=2020, rid="b", species_id="999999"),
        ]
        with self.assertRaises(ValueError):
            records_by_year(mixed)
        with self.assertRaises(ValueError):
            year_range(mixed)
        self.assertEqual(
            records_by_year_by_species(mixed),
            {
                "5088": [{"year": 2020, "count": 1}],
                "999999": [{"year": 2020, "count": 1}],
            },
        )

    def test_the_map_arithmetic_closes(self):
        records = [
            rec("ST585725", rid="a"),
            rec("ST57", rid="b"),
            rec("junk", precision=1000, rid="c"),
        ]
        report = build_cells(records)
        self.assertTrue(reconciles(report, records))
        self.assertEqual(
            report.records_aggregated + report.records_skipped_unpublishable, len(records)
        )

    def test_cell_totals_equal_the_aggregated_count(self):
        records = [rec("ST585725", rid=str(i)) for i in range(7)]
        report = build_cells(records)
        self.assertEqual(sum(c.record_count for c in report.cells), report.records_aggregated)


if __name__ == "__main__":
    unittest.main(verbosity=1)
