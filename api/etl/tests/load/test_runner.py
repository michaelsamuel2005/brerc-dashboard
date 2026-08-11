import pytest
from unittest.mock import MagicMock, patch

from etl.load.runner import run_load

# --- run_load tests ---

def test_run_load_triggers_initial_load():
    mock_df = MagicMock()
    mock_connection = MagicMock()
    mock_ui_map = {"table_name": "occurrence_public"}
    expected_result = {"status": "initial_success"}

    # Patch should_run_initial_load, the database state helper, and the loaders
    with patch("etl.load.runner.should_run_initial_load", return_value=True), \
         patch("etl.load.runner._get_destination_table_status", return_value=(True, False)), \
         patch("etl.load.runner.initial_load", return_value=expected_result, create=True) as mock_initial, \
         patch("etl.load.runner.incremental_load", create=True) as mock_incremental:

        result = run_load(
            mock_df,
            mock_connection,
            mock_ui_map,
        )

    mock_initial.assert_called_once_with(
        mock_df,
        mock_connection,
        table_name="occurrence_public",
    )
    mock_incremental.assert_not_called()
    assert result == expected_result


def test_run_load_triggers_incremental_load():
    mock_df = MagicMock()
    mock_connection = MagicMock()
    mock_ui_map = {"table_name": "occurrence_public"}
    expected_result = {"status": "incremental_success"}

    with patch("etl.load.runner.should_run_initial_load", return_value=False), \
         patch("etl.load.runner._get_destination_table_status", return_value=(True, True)), \
         patch("etl.load.runner.initial_load", create=True) as mock_initial, \
         patch("etl.load.runner.incremental_load", return_value=expected_result, create=True) as mock_incremental:

        result = run_load(
            mock_df,
            mock_connection,
            mock_ui_map,
        )

    mock_incremental.assert_called_once_with(
        mock_df,
        mock_connection,
        mock_ui_map,
        table_name="occurrence_public",
    )
    mock_initial.assert_not_called()
    assert result == expected_result