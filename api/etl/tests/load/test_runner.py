import pytest
from unittest.mock import MagicMock, patch

from etl.load.runner import ( 
    run_load,
)

# --- run_load tests ---

def test_run_load_triggers_initial_load():
    # Confirms the function delegates to initial_load when conditions mandate a full rebuild.
    # Expects initial_load to be called with the dataframe and connection, returning its result, else fails.
    mock_df = MagicMock()
    mock_connection = MagicMock()
    mock_ui_map = MagicMock()
    expected_result = {"status": "initial_success"}

    # Notice the create=True on initial_load and incremental_load patches
    with patch("etl.load.runner.should_run_initial_load", return_value=True), \
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
    )
    mock_incremental.assert_not_called()
    assert result == expected_result


def test_run_load_triggers_incremental_load():
    # Confirms the function delegates to incremental_load for standard append operations.
    # Expects incremental_load to be called with the dataframe, connection, and UI map, else fails.
    mock_df = MagicMock()
    mock_connection = MagicMock()
    mock_ui_map = MagicMock()
    expected_result = {"status": "incremental_success"}

    # Notice the create=True on initial_load and incremental_load patches
    with patch("etl.load.runner.should_run_initial_load", return_value=False), \
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
    )
    mock_initial.assert_not_called()
    assert result == expected_result