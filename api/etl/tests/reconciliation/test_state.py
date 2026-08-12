from unittest.mock import MagicMock

from etl.reconciliation.state import (  # Update with your actual module path if different
    get_ui_map,
)

# --- get_ui_map tests ---


def test_get_ui_map_returns_id_modified_dictionary():
    # Confirms database rows are converted into a record_id to date_mdb_modified dictionary.
    # Expects IDs to be stored as strings to match unique_no key format, else fails.
    connection = MagicMock()

    # Mocks the database cursor returning two rows with record_id and date_mdb_modified
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        {
            "record_id": 1,
            "date_mdb_modified": "2026-01-01 12:00:00",
        },
        {
            "record_id": 2,
            "date_mdb_modified": "2026-01-02 12:00:00",
        },
    ]

    result = get_ui_map(connection)

    assert result == {
        "1": "2026-01-01 12:00:00",
        "2": "2026-01-02 12:00:00",
    }


def test_get_ui_map_returns_empty_dictionary_when_no_records():
    # Confirms an empty database gracefully returns an empty mapping without errors.
    # Expects an empty dictionary {} to be returned when fetchall yields no rows, else fails.
    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    result = get_ui_map(connection)

    assert result == {}