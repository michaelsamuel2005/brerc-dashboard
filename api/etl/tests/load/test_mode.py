from unittest.mock import patch
import pytest

from etl.load.mode import (  # Update with your actual module path if different
    should_run_initial_load,
)

# --- should_run_initial_load tests ---


def test_initial_load_when_incremental_disabled():
    # Confirms config can force a full initial load.
    # Expects True to be returned even if the database already contains data, else fails.
    with patch(
        "etl.load.mode.CONFIG",
        {
            "load": {
                "incremental_check": False,
            }
        },
    ):
        result = should_run_initial_load(
            table_exists=True,
            table_has_rows=True,
        )

    assert result is True


def test_initial_load_when_table_does_not_exist():
    # Confirms a missing destination table requires an initial load.
    # Expects True to be returned to trigger table creation and full load, else fails.
    with patch(
        "etl.load.mode.CONFIG",
        {
            "load": {
                "incremental_check": True,
            }
        },
    ):
        result = should_run_initial_load(
            table_exists=False,
            table_has_rows=False,
        )

    assert result is True


def test_initial_load_when_table_is_empty():
    # Confirms an empty destination table requires an initial load.
    # Expects True to be returned when the table exists but has no records, else fails.
    with patch(
        "etl.load.mode.CONFIG",
        {
            "load": {
                "incremental_check": True,
            }
        },
    ):
        result = should_run_initial_load(
            table_exists=True,
            table_has_rows=False,
        )

    assert result is True


def test_incremental_load_when_database_contains_data():
    # Confirms an existing populated database uses incremental loading when enabled.
    # Expects False to be returned so the ETL process runs incrementally, else fails.
    with patch(
        "etl.load.mode.CONFIG",
        {
            "load": {
                "incremental_check": True,
            }
        },
    ):
        result = should_run_initial_load(
            table_exists=True,
            table_has_rows=True,
        )

    assert result is False
