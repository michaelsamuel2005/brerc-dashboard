"""Strict configuration and operator boundary for BRERC release loading.

Importing this package requires only the Python standard library. PyYAML is
loaded only when configuration is parsed, and the PostgreSQL coordinator is
loaded only after the requested load mode and configuration pass their gates.
"""

from .config import (
    BRERC_TARGET_APPLICATION_NAME,
    LOADER_CONFIG_VERSION,
    MAX_SPECIES_DICTIONARY_BYTES,
    LoaderConfig,
    LoaderRuntimeConfig,
    PublicationConfig,
    ReconciliationConfig,
    SpeciesDictionaryConfig,
    TargetConnectionConfig,
    load_loader_config,
)
from .errors import (
    IncrementalSourceContractBlocked,
    LoaderConfigurationError,
    LoaderCoordinatorUnavailable,
    LoaderError,
    LoaderExecutionFailed,
)
from .models import LoaderRunReport, LoadMode, RunState
from .species_dictionary import parse_species_dictionary_artifact

__all__ = [
    "BRERC_TARGET_APPLICATION_NAME",
    "LOADER_CONFIG_VERSION",
    "MAX_SPECIES_DICTIONARY_BYTES",
    "IncrementalSourceContractBlocked",
    "LoadMode",
    "LoaderConfig",
    "LoaderConfigurationError",
    "LoaderCoordinatorUnavailable",
    "LoaderError",
    "LoaderExecutionFailed",
    "LoaderRunReport",
    "LoaderRuntimeConfig",
    "PublicationConfig",
    "ReconciliationConfig",
    "RunState",
    "SpeciesDictionaryConfig",
    "TargetConnectionConfig",
    "load_loader_config",
    "parse_species_dictionary_artifact",
]
