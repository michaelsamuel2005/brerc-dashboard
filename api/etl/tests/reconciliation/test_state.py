from unittest.mock import MagicMock

from etl.reconciliation.state import get_ui_map


def test_get_ui_map_returns_id_hash_dictionary():
    """
    Confirms database rows are converted into a record_id ->
    content_hash dictionary.

    IDs are stored as strings because occurrence_public.record_id
    is a TEXT database key.
    """

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
        "1": "hash1",
        "2": "hash2",
    }


def test_get_ui_map_returns_empty_dictionary_when_no_records():
    """
    Confirms an empty database returns an empty mapping.
    """

    connection = MagicMock()

    connection.cursor.return_value.__enter__.return_value.fetchall.return_value = []

    result = get_ui_map(connection)

    assert result == {}