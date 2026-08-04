from pathlib import Path
import yaml

DEFAULT_CONFIG_PATH = (
    Path(__file__).parents[3] / "config" / "safety.yaml"
)

def load_safety_config(path=None):

    if path is None:
        path = DEFAULT_CONFIG_PATH

    with open(path, "r") as file:
        return yaml.safe_load(file)