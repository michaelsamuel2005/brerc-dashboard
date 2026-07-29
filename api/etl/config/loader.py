import yaml
from pathlib import Path


def load_safety_config(path):

    with open(path) as file:
        return yaml.safe_load(file)