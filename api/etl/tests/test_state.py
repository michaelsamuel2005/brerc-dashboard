from unittest.mock import MagicMock

from etl.reconciliation.state import get_ui_map


def test_get_ui_map_returns_record_id_to_content_hash():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value

    cursor.fetchall.return_value = [
        {
            "record_id": 1,
            "content_hash": "hash-one",
        },
        {
            "record_id": 2,
            "content_hash": "hash-two",
        },
    ]

    result = get_ui_map(connection)

    assert result == {
        1: "hash-one",
        2: "hash-two",
    }

    cursor.execute.assert_called_once_with(
        """
                SELECT record_id, content_hash
                FROM occurrence_public
                """
    )