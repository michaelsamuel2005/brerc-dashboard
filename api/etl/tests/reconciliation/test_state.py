import pytest
from unittest.mock import MagicMock

from etl.reconciliation.state import get_ui_map


# --- get_ui_map tests ---

def test_get_ui_map_returns_id_hash_dictionary():
    # Confirms database rows are converted into a record_id ->
    # content_hash dictionary.
    # Expects the correct mapping, else fails.
    connection = MagicMock()

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
        1: "hash1",
        2: "hash2",
    }


def test_get_ui_map_returns_empty_dictionary_when_no_rows():
    # Confirms an empty query result produces an empty dictionary.
    # Expects {}, else fails.
    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    result = get_ui_map(connection)

    assert result == {}


def test_get_ui_map_executes_expected_query():
    # Confirms the occurrence_public table is queried.
    # Expects execute() to be called once, else fails.
    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    get_ui_map(connection)

    connection.cursor.return_value.__enter__.return_value.execute.assert_called_once()