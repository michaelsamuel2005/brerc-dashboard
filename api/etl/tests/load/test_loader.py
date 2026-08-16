from unittest.mock import patch, mock_open

from etl.load.loader import (
    load_safety_config,
    DEFAULT_CONFIG_PATH,
)

# --- load_safety_config tests ---


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_default_path(mock_file, mock_yaml):
    # Confirms the default path is used when no explicit path is provided.
    # Expects the file mock to be called with DEFAULT_CONFIG_PATH, else fails.

    mock_yaml.return_value = {"suppression_threshold": 5}

    result = load_safety_config()

    mock_file.assert_called_once_with(DEFAULT_CONFIG_PATH, "r")
    assert result == {"suppression_threshold": 5}


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_custom_path(mock_file, mock_yaml):
    # Confirms a custom path overrides the default.
    # Expects the file mock to be opened with the exact provided path, else fails.

    custom_path = "/custom/path/to/config.yaml"
    load_safety_config(path=custom_path)

    mock_file.assert_called_once_with(custom_path, "r")
