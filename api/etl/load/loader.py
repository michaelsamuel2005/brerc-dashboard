"""
Loads configuration settings from YAML files.
"""

from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "safety.yaml"


def load_safety_config(path=None):
    """Loads the safety configuration YAML file, falling back to an example file if needed."""
    if path is None:
        config_path = DEFAULT_CONFIG_PATH

        # Fall back to the example config if the real one isn't present
        if not config_path.exists():
            example_path = config_path.with_suffix(config_path.suffix + ".example")

            if example_path.exists():
                config_path = example_path
            else:
                raise FileNotFoundError(
                    f"Neither configuration file {config_path} "
                    f"nor fallback {example_path} could be found."
                )
    else:
        config_path = path

    with open(config_path, "r") as file:
        return yaml.safe_load(file)
