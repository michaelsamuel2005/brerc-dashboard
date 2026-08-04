from unittest.mock import patch

from etl.load.mode import should_run_initial_load


def test_initial_load_when_incremental_disabled():
    """
    Confirms config can force a full initial load.

    Even if the database already contains data,
    incremental_check=False should trigger initial load.
    """

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
    """
    Confirms a missing destination table requires
    an initial load.
    """

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
    """
    Confirms an empty destination table requires
    an initial load.
    """

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
    """
    Confirms an existing populated database uses
    incremental loading when enabled.
    """

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