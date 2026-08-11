"""
Local fixtures for the integration test suite.

test_nightly_job_end_to_end runs a real ETL reconciliation pass, which purges
any occurrence_public rows not present in its mocked source data — including
the shared B0/B6 sample rows. This autouse fixture re-seeds those sample rows
after the test runs, so the shared brerc_ui database is left the way every
other test expects to find it.
"""

import pytest

from app.db import get_connection


def _reseed_sample_data():
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM occurrence_public;")
            cur.execute("DELETE FROM distribution_cell;")
            cur.execute("DELETE FROM provenance;")
            cur.execute("DELETE FROM species;")

            cur.execute(
                """
                INSERT INTO species (species_id, scientific_name, common_name, species_group,
                                     record_count, first_year, last_year, has_image,
                                     "Load", "Load_date") VALUES
                    (100001, 'Erithacus rubecula', 'Robin',       'birds',      3, 2022, 2024, false, 'initial', '2026-08-09 00:00:00'),
                    (100002, 'Bufo bufo',          'Common Toad', 'amphibians', 2, 2021, 2024, false, 'initial', '2026-08-09 00:00:00'),
                    (100003, 'Lutra lutra',        'Otter',       'mammals',    2, 2024, 2025, false, 'initial', '2026-08-09 00:00:00');
                """
            )

            cur.execute(
                """
                INSERT INTO occurrence_public (record_id, species_id, record_year, grid_ref,
                                               precision_metres, locality, verified,
                                               content_hash, "Load", "Load_date") VALUES
                    (1, 100001, 2024, 'ST5872', 1000,  'Bristol (ST58)',               true,  md5('1|100001|2024|ST5872'), 'initial', '2026-08-09 00:00:00'),
                    (2, 100001, 2023, 'ST5973', 1000,  'Bristol (ST59)',               true,  md5('2|100001|2023|ST5973'), 'initial', '2026-08-09 00:00:00'),
                    (3, 100001, 2022, 'ST5771', 1000,  'Bristol (ST57)',               false, md5('3|100001|2022|ST5771'), 'initial', '2026-08-09 00:00:00'),
                    (4, 100002, 2024, 'ST6074', 1000,  'South Gloucestershire (ST60)', true,  md5('4|100002|2024|ST6074'), 'initial', '2026-08-09 00:00:00'),
                    (5, 100002, 2021, 'ST61',   10000, 'South Gloucestershire (ST61)', true,  md5('5|100002|2021|ST61'),   'initial', '2026-08-09 00:00:00'),
                    (6, 100003, 2025, 'ST5',    10000, 'Bristol area (ST)',            true,  md5('6|100003|2025|ST5'),    'initial', '2026-08-09 00:00:00'),
                    (7, 100003, 2024, 'ST5',    10000, 'Bristol area (ST)',            false, md5('7|100003|2024|ST5'),    'initial', '2026-08-09 00:00:00');
                """
            )

            cur.execute(
                """
                INSERT INTO distribution_cell (cell_id, species_id, record_year, precision_metres,
                                               record_count, verified_count, geom,
                                               "Load", "Load_date") VALUES
                    ('ST5872', 100001, 2024, 1000,  1, 1, ST_SetSRID(ST_MakeEnvelope(-2.600, 51.450, -2.586, 51.459), 4326), 'initial', '2026-08-09 00:00:00'),
                    ('ST5973', 100001, 2023, 1000,  1, 1, ST_SetSRID(ST_MakeEnvelope(-2.586, 51.459, -2.571, 51.468), 4326), 'initial', '2026-08-09 00:00:00'),
                    ('ST5771', 100001, 2022, 1000,  1, 0, ST_SetSRID(ST_MakeEnvelope(-2.615, 51.441, -2.600, 51.450), 4326), 'initial', '2026-08-09 00:00:00'),
                    ('ST6074', 100002, 2024, 1000,  1, 1, ST_SetSRID(ST_MakeEnvelope(-2.571, 51.468, -2.556, 51.477), 4326), 'initial', '2026-08-09 00:00:00'),
                    ('ST61',   100002, 2021, 10000, 1, 1, ST_SetSRID(ST_MakeEnvelope(-2.600, 51.500, -2.450, 51.590), 4326), 'initial', '2026-08-09 00:00:00'),
                    ('ST5',    100003, 2025, 10000, 2, 1, ST_SetSRID(ST_MakeEnvelope(-2.750, 51.400, -2.600, 51.490), 4326), 'initial', '2026-08-09 00:00:00');
                """
            )

            cur.execute(
                """
                INSERT INTO provenance (id, sources, caveats, last_updated, sensitivity_policy_summary,
                                        "Load", "Load_date") VALUES
                    (1,
                     ARRAY['Bristol Regional Environmental Records Centre (BRERC)', 'NBN Atlas partners'],
                     ARRAY['Absence of records does not mean absence of a species.',
                           'Sensitive-species locations are generalised to protect them.',
                           'Only accepted records are shown on the public dashboard.'],
                     DATE '2026-07-25',
                     'Locations of sensitive species, badger setts and Schedule 1 bird nest sites are generalised to a coarse grid. Recorder names are not published.',
                     'initial', '2026-08-09 00:00:00');
                """
            )

        conn.commit()


@pytest.fixture(autouse=True)
def reseed_sample_data_after_pipeline_tests():
    yield
    _reseed_sample_data()