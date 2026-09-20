from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

from etl.load.loader import (
    DEFAULT_CONFIG_PATH,
    load_safety_config,
)

# --- load_safety_config tests ---


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_default_path(mock_file, mock_yaml):
    # Confirms the default path is used when no explicit path is provided.
    # Expects the file mock to be called with DEFAULT_CONFIG_PATH, else fails.
    #
    # Path.exists is patched rather than left to the real filesystem. Without
    # it this test passes or fails depending on whether the developer happens
    # to have a config/safety.yaml: with one it takes the default path, without
    # one it falls through to the .example and opens a different file. That is
    # the machine answering, not the code — and it is why this test failed on a
    # fresh checkout and in CI while passing locally for whoever wrote it.

    mock_yaml.return_value = {"suppression_threshold": 5}

    with patch.object(Path, "exists", return_value=True):
        result = load_safety_config()

    mock_file.assert_called_once_with(DEFAULT_CONFIG_PATH, "r")
    assert result == {"suppression_threshold": 5}


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_falls_back_to_the_example(mock_file, mock_yaml):
    # The fallback branch, asserted deliberately rather than reached by accident.
    # This is what actually runs on a fresh checkout, so it is worth pinning:
    # the loader must open safety.yaml.example, not fail and not open something
    # else.

    mock_yaml.return_value = {"suppression_threshold": 5}
    example_path = DEFAULT_CONFIG_PATH.with_suffix(DEFAULT_CONFIG_PATH.suffix + ".example")

    # Only the .example exists; the real config does not.
    def only_the_example_exists(self):
        return self.suffix == ".example"

    with patch.object(Path, "exists", only_the_example_exists):
        result = load_safety_config()

    mock_file.assert_called_once_with(example_path, "r")
    assert result == {"suppression_threshold": 5}


def test_example_config_disables_the_legacy_incremental_path():
    example_path = DEFAULT_CONFIG_PATH.with_suffix(DEFAULT_CONFIG_PATH.suffix + ".example")

    config = load_safety_config(path=example_path)

    assert config["load"]["incremental_check"] is False


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_raises_when_no_config_exists(mock_file, mock_yaml):
    # With neither file present the loader must say so, naming both paths,
    # rather than opening nothing and returning None for every setting — the
    # safety rules (D0 floor, sensitive resolution, flagged record types) are
    # read straight out of this config.

    with patch.object(Path, "exists", return_value=False):
        with pytest.raises(FileNotFoundError) as raised:
            load_safety_config()

    assert "safety.yaml" in str(raised.value)
    assert "safety.yaml.example" in str(raised.value)
    mock_file.assert_not_called()


@patch("etl.load.loader.yaml.safe_load")
@patch("builtins.open", new_callable=mock_open)
def test_load_safety_config_uses_custom_path(mock_file, mock_yaml):
    # Confirms a custom path overrides the default.
    # Expects the file mock to be opened with the exact provided path, else fails.

    custom_path = "/custom/path/to/config.yaml"
    load_safety_config(path=custom_path)

    mock_file.assert_called_once_with(custom_path, "r")
