from unittest.mock import MagicMock

from etl.reconciliation.state import (  # Update with your actual module path if different
    get_ui_map,
)

# --- get_ui_map tests ---


def test_get_ui_map_returns_id_hash_dictionary():
    # Confirms database rows are converted into a record_id to content_hash dictionary.
    # Expects IDs to be stored as strings to match the occurrence_public TEXT key format, else fails.
    connection = MagicMock()

    # Mocks the database cursor returning two rows
    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        {
            "record_id": 1,
            "content_hash": "hash1",
        },
        {
            "record_id": 2,
            "content_hash": "hash2",
        },
    ]

    result = get_ui_map(connection)

    assert result == {
        "1": "hash1",
        "2": "hash2",
    }


def test_get_ui_map_returns_empty_dictionary_when_no_records():
    # Confirms an empty database gracefully returns an empty mapping without errors.
    # Expects an empty dictionary {} to be returned when fetchall yields no rows, else fails.
    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    result = get_ui_map(connection)

    assert result == {}
