#!/usr/bin/env python3
"""Manual synthetic five-million-row acceptance gate for the initial loader.

This is deliberately not part of ordinary CI. It connects only to the two
synthetic TLS databases provisioned by the manual scale workflow, exercises the
real trusted source connector and destination store, and emits one allow-listed
JSON evidence document. Raw rows, connection parameters, paths and adapter
exceptions are never emitted.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import resource
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from brerc_loader import postgres as loader_coordinator  # noqa: E402
from brerc_loader.config import SpeciesDictionaryConfig  # noqa: E402
from brerc_loader.errors import LoaderCandidateInvalid, LoaderError  # noqa: E402
from brerc_loader.postgres import _PostgreSQLTargetStore  # noqa: E402
from brerc_loader.species_dictionary import parse_species_dictionary_artifact  # noqa: E402
from loader_tests.test_postgis16_destination_integration import (  # noqa: E402
    TestPostGIS16DestinationIntegration,
    _loader_config,
    _policy,
)

SCALE_ROWS = 5_000_000
BATCH_SIZE = 5_000
CONFIRMATION = "RUN_EXACTLY_5000000_SYNTHETIC_ROWS"
EVIDENCE_VERSION = "brerc-loader-scale-evidence-v1"
MAX_WORKLOAD_SECONDS = 18_000
SOURCE_IMAGE = (
    "postgres:16.10-bookworm@"
    "sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74"
)
TARGET_IMAGE = (
    "postgis/postgis:16-3.5@sha256:cfbd2d2a5ecded5af7afaad719fa2117096f59ac8d0d9430e157eeffcd82da2e"
)
EXPECTED_COUNTS = {
    "sourceRows": SCALE_ROWS,
    "eligibleBeforeSuppression": SCALE_ROWS - 1,
    "transformWithheld": 1,
    "suppressionWithheld": 2,
    "publishedBasis": SCALE_ROWS - 3,
    "species": 102,
    "distributionCells": 102,
    "speciesYears": 102,
    "publicRecords": 0,
}
REPO_ROOT = API_ROOT.parent
SCALE_FIXTURE = REPO_ROOT / "api/loader_tests/postgres16_scale_source_fixture.sql"
MIGRATION = REPO_ROOT / "db/migrations/0001_publication_store.sql"
ROLES_SQL = REPO_ROOT / "db/roles.sql"
WORKFLOW = REPO_ROOT / ".github/workflows/loader-scale-acceptance.yml"


def _scale_species_dictionary_artifact() -> bytes:
    rows = [
        "SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE",
        "SYNTH-SCALE-SPARSE,Synthetic sparse species,Synthetic sparse,No",
        "SYNTH-SCALE-UNLIC,Synthetic unlicensed species,Synthetic unlicensed,No",
        "SYNTH-SCALE-SENS,Synthetic sensitive species,Synthetic sensitive,Yes",
        ("SYNTH-SCALE-ORDINARY,Synthetic ordinary control species,Synthetic ordinary control,No"),
    ]
    rows.extend(
        f"SYNTH-SCALE-{number:03d},Synthetic bulk species {number:02d},"
        f"Synthetic bulk {number:02d},No"
        for number in range(100)
    )
    return ("\n".join(rows) + "\n").encode("utf-8")


SCALE_SPECIES_DICTIONARY_ARTIFACT = _scale_species_dictionary_artifact()


def _scale_species_dictionary():
    return parse_species_dictionary_artifact(SCALE_SPECIES_DICTIONARY_ARTIFACT)


def _scale_policy(*, dictionary: Any, allowed_licence_values: frozenset[str]) -> Any:
    policy = _policy(threshold=3, allowed_licence_values=allowed_licence_values)
    policy = dataclasses.replace(
        policy,
        species_dictionary_sha256=dictionary.digest(),
        approval_digest=None,
    )
    policy = dataclasses.replace(policy, approval_digest=policy._expected_approval_digest())
    policy.validate()
    policy.assert_approved()
    return policy


class ScaleAcceptanceError(RuntimeError):
    """Fixed-boundary failure; its message is never rendered."""


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ScaleAcceptanceError


@dataclass(frozen=True)
class Budgets:
    total_seconds: float
    finalize_seconds: float
    activate_seconds: float
    cleanup_seconds: float
    rss_mib: float
    source_temp_mib: float
    target_temp_mib: float
    target_wal_mib: float
    target_db_growth_mib: float
    min_free_disk_mib: float

    def as_document(self) -> dict[str, float]:
        return {
            "maxActivateSeconds": self.activate_seconds,
            "maxCleanupSeconds": self.cleanup_seconds,
            "maxFinalizeSeconds": self.finalize_seconds,
            "maxProcessRssMiB": self.rss_mib,
            "maxSourceTempMiB": self.source_temp_mib,
            "maxTargetDatabaseGrowthMiB": self.target_db_growth_mib,
            "maxTargetTempMiB": self.target_temp_mib,
            "maxTargetWalMiB": self.target_wal_mib,
            "maxTotalSeconds": self.total_seconds,
            "minFreeDiskMiB": self.min_free_disk_mib,
        }


@dataclass
class PhaseMeasurements:
    activation_started: threading.Event = field(default_factory=threading.Event)
    candidate_staged: threading.Event = field(default_factory=threading.Event)
    complete_observed: threading.Event = field(default_factory=threading.Event)
    finalize_seconds: list[float] = field(default_factory=list)
    activate_seconds: list[float] = field(default_factory=list)
    cleanup_seconds: list[float] = field(default_factory=list)
    stage_batch_sizes: list[int] = field(default_factory=list)


@dataclass
class ResourceMeasurements:
    target_database_peak_bytes: int
    minimum_free_disk_bytes: int
    samples: int = 0
    failed: bool = False


@dataclass(frozen=True)
class DatabaseSnapshot:
    database_bytes: int
    temp_bytes: int
    wal_lsn: str


class _MeasuredStore(_PostgreSQLTargetStore):
    def __init__(
        self,
        config: object,
        measurements: PhaseMeasurements,
        *,
        retain_cleanup_debt: bool,
    ) -> None:
        super().__init__(config)  # type: ignore[arg-type]
        self._scale_measurements = measurements
        self._scale_retain_cleanup_debt = retain_cleanup_debt

    def stage_batch(self, handle: object, batch: tuple[object, ...]) -> None:
        super().stage_batch(handle, batch)  # type: ignore[arg-type]
        self._scale_measurements.stage_batch_sizes.append(len(batch))
        self._scale_measurements.candidate_staged.set()

    def finalize(self, *args: object, **kwargs: object):
        started = time.monotonic()
        try:
            return super().finalize(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            self._scale_measurements.finalize_seconds.append(time.monotonic() - started)

    def activate(self, *args: object, **kwargs: object):
        self._scale_measurements.activation_started.set()
        started = time.monotonic()
        try:
            return super().activate(*args, **kwargs)  # type: ignore[arg-type]
        finally:
            self._scale_measurements.activate_seconds.append(time.monotonic() - started)

    def _discard_inactive_release(self, release_id: object) -> None:
        started = time.monotonic()
        try:
            super()._discard_inactive_release(release_id)  # type: ignore[arg-type]
        finally:
            self._scale_measurements.cleanup_seconds.append(time.monotonic() - started)

    def _discard_failed_candidate(self, handle: object) -> None:
        if self._scale_retain_cleanup_debt:
            # Controlled fault injection: fail_candidate has already committed
            # terminal truth/outbox/cleanup_pending. Simulate process loss before
            # the best-effort bulk purge so the next lock owner must resume it.
            raise ScaleAcceptanceError
        super()._discard_failed_candidate(handle)  # type: ignore[arg-type]


def _positive_number(raw: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ScaleAcceptanceError from None
    if not math.isfinite(value) or value <= 0:
        raise ScaleAcceptanceError
    return value


def _arguments(argv: Sequence[str]) -> tuple[Path, Budgets]:
    parser = _SafeParser(add_help=True)
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--evidence-out", required=True, type=Path)
    for option in (
        "max-total-seconds",
        "max-finalize-seconds",
        "max-activate-seconds",
        "max-cleanup-seconds",
        "max-rss-mib",
        "max-source-temp-mib",
        "max-target-temp-mib",
        "max-target-wal-mib",
        "max-target-db-growth-mib",
        "min-free-disk-mib",
    ):
        parser.add_argument(f"--{option}", required=True, type=_positive_number)
    namespace = parser.parse_args(list(argv))
    if namespace.confirm != CONFIRMATION:
        raise ScaleAcceptanceError
    total_seconds = namespace.max_total_seconds
    if total_seconds < 60 or total_seconds > MAX_WORKLOAD_SECONDS:
        raise ScaleAcceptanceError
    output = namespace.evidence_out
    if output.exists():
        raise ScaleAcceptanceError
    return output, Budgets(
        total_seconds=total_seconds,
        finalize_seconds=namespace.max_finalize_seconds,
        activate_seconds=namespace.max_activate_seconds,
        cleanup_seconds=namespace.max_cleanup_seconds,
        rss_mib=namespace.max_rss_mib,
        source_temp_mib=namespace.max_source_temp_mib,
        target_temp_mib=namespace.max_target_temp_mib,
        target_wal_mib=namespace.max_target_wal_mib,
        target_db_growth_mib=namespace.max_target_db_growth_mib,
        min_free_disk_mib=namespace.min_free_disk_mib,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_identity() -> tuple[str, bool]:
    git = shutil.which("git")
    if git is None:
        raise ScaleAcceptanceError
    commit = subprocess.run(  # noqa: S603
        [git, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    status = subprocess.run(  # noqa: S603
        [git, "-C", str(REPO_ROOT), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ScaleAcceptanceError
    return commit, not bool(status)


def _rss_mib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        return value / (1024 * 1024)
    return value / 1024


def _snapshot(connection: Any) -> DatabaseSnapshot:
    row = connection.execute(
        "SELECT pg_database_size(current_database()) AS database_bytes, "
        "COALESCE((SELECT temp_bytes FROM pg_stat_database "
        "WHERE datname = current_database()), 0) AS temp_bytes, "
        "pg_current_wal_lsn()::text AS wal_lsn"
    ).fetchone()
    if not isinstance(row, dict):
        raise ScaleAcceptanceError
    database_bytes = row.get("database_bytes")
    temp_bytes = row.get("temp_bytes")
    wal_lsn = row.get("wal_lsn")
    if (
        type(database_bytes) is not int
        or type(temp_bytes) is not int
        or not isinstance(wal_lsn, str)
    ):
        raise ScaleAcceptanceError
    return DatabaseSnapshot(database_bytes, temp_bytes, wal_lsn)


@contextmanager
def _sample_resources(
    base: Any,
    evidence_path: Path,
    initial: DatabaseSnapshot,
) -> Iterator[ResourceMeasurements]:
    measurements = ResourceMeasurements(
        target_database_peak_bytes=initial.database_bytes,
        minimum_free_disk_bytes=shutil.disk_usage(evidence_path.parent).free,
    )
    stop = threading.Event()

    def observe() -> None:
        try:
            with base._admin_connection() as connection:
                while not stop.is_set():
                    row = connection.execute(
                        "SELECT pg_database_size(current_database()) AS database_bytes"
                    ).fetchone()
                    if not isinstance(row, dict) or type(row.get("database_bytes")) is not int:
                        measurements.failed = True
                        return
                    measurements.target_database_peak_bytes = max(
                        measurements.target_database_peak_bytes,
                        row["database_bytes"],
                    )
                    measurements.minimum_free_disk_bytes = min(
                        measurements.minimum_free_disk_bytes,
                        shutil.disk_usage(evidence_path.parent).free,
                    )
                    measurements.samples += 1
                    stop.wait(1.0)
        except Exception:
            measurements.failed = True

    thread = threading.Thread(target=observe, name="scale-resource-sampler", daemon=True)
    thread.start()
    try:
        yield measurements
    finally:
        stop.set()
        thread.join(timeout=10)
        if thread.is_alive() or measurements.failed or measurements.samples < 1:
            raise ScaleAcceptanceError


def _wal_bytes(connection: Any, before: str, after: str) -> int:
    row = connection.execute(
        "SELECT pg_wal_lsn_diff(%s::pg_lsn, %s::pg_lsn) AS bytes",
        (after, before),
    ).fetchone()
    if not isinstance(row, dict) or not isinstance(row.get("bytes"), Decimal | int):
        raise ScaleAcceptanceError
    value = int(row["bytes"])
    if value < 0:
        raise ScaleAcceptanceError
    return value


def _durability(connection: Any, *, postgis: bool) -> dict[str, str]:
    expression = (
        "SELECT current_setting('server_version_num') AS server_version_num, "
        "current_setting('fsync') AS fsync, "
        "current_setting('full_page_writes') AS full_page_writes, "
        "current_setting('synchronous_commit') AS synchronous_commit, "
        "current_setting('shared_buffers') AS shared_buffers, "
        "current_setting('work_mem') AS work_mem, "
        "current_setting('maintenance_work_mem') AS maintenance_work_mem, "
        "current_setting('temp_file_limit') AS temp_file_limit, "
        "current_setting('max_wal_size') AS max_wal_size"
    )
    row = connection.execute(expression).fetchone()
    if not isinstance(row, dict):
        raise ScaleAcceptanceError
    result = {key: str(value) for key, value in row.items()}
    if postgis:
        version = connection.execute("SELECT public.postgis_lib_version() AS version").fetchone()
        if not isinstance(version, dict):
            raise ScaleAcceptanceError
        result["postgis_version"] = str(version.get("version"))
    if (
        not result["server_version_num"].startswith("16")
        or result["fsync"] != "on"
        or result["full_page_writes"] != "on"
        or result["synchronous_commit"] != "on"
        or (postgis and not result["postgis_version"].startswith("3.5"))
    ):
        raise ScaleAcceptanceError
    return result


def _runner_capacity() -> dict[str, int]:
    cpu_count = os.cpu_count()
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        raise ScaleAcceptanceError from None
    if (
        type(cpu_count) is not int
        or cpu_count < 1
        or type(page_size) is not int
        or page_size < 1
        or type(page_count) is not int
        or page_count < 1
    ):
        raise ScaleAcceptanceError
    return {
        "logicalCpuCount": cpu_count,
        "physicalMemoryMiB": (page_size * page_count) // (1024 * 1024),
    }


def _source_oracle(connection: Any) -> dict[str, int]:
    row = connection.execute(
        "SELECT count(*) AS rows, count(unique_no) AS nonnull_ids, "
        "count(DISTINCT unique_no) AS distinct_ids, "
        "count(*) FILTER (WHERE licence = 'n') AS unlicensed, "
        "count(*) FILTER (WHERE sensitive = 'Yes') AS sensitive, "
        "count(*) FILTER (WHERE species_no = 'SYNTH-SCALE-SPARSE') AS sparse, "
        "count(DISTINCT grid_ref) FILTER "
        "(WHERE species_no = 'SYNTH-SCALE-SPARSE') AS sparse_cells, "
        "count(*) FILTER (WHERE species_no = 'SYNTH-SCALE-SENS') "
        "AS sensitive_species_rows, "
        "count(DISTINCT grid_ref) FILTER "
        "(WHERE species_no = 'SYNTH-SCALE-SENS') AS sensitive_cells, "
        "count(*) FILTER (WHERE species_no = 'SYNTH-SCALE-ORDINARY') "
        "AS ordinary_rows, "
        "count(DISTINCT grid_ref) FILTER "
        "(WHERE species_no = 'SYNTH-SCALE-ORDINARY') AS ordinary_cells, "
        "count(*) FILTER (WHERE place = "
        "'SYNTHETIC-PRIVATE-SCALE-PLACE-MUST-NOT-CROSS' AND comments = "
        "'SYNTHETIC-PRIVATE-SCALE-COMMENT-MUST-NOT-CROSS') AS private_sentinels "
        "FROM dashboard.main_data_dash"
    ).fetchone()
    if not isinstance(row, dict) or any(type(value) is not int for value in row.values()):
        raise ScaleAcceptanceError
    expected = {
        "distinct_ids": SCALE_ROWS,
        "nonnull_ids": SCALE_ROWS,
        "ordinary_cells": 1,
        "ordinary_rows": 3,
        "private_sentinels": SCALE_ROWS,
        "rows": SCALE_ROWS,
        "sensitive": 3,
        "sensitive_cells": 1,
        "sensitive_species_rows": 3,
        "sparse": 2,
        "sparse_cells": 1,
        "unlicensed": 1,
    }
    if row != expected:
        raise ScaleAcceptanceError
    return expected


def _reset_statistics(connection: Any) -> None:
    connection.execute("SELECT pg_stat_reset()")


def _scale_configs(base: Any, policy: Any, remaining_seconds: float) -> tuple[Any, Any]:
    total_seconds = math.floor(remaining_seconds)
    if total_seconds < 60:
        raise ScaleAcceptanceError
    statement_ms = min(3_600_000, total_seconds * 1_000)
    loader = _loader_config(policy)
    loader = dataclasses.replace(
        loader,
        species_dictionary=SpeciesDictionaryConfig(
            csv_path=Path("/synthetic/scale-species-dictionary.csv"),
            expected_raw_sha256=hashlib.sha256(SCALE_SPECIES_DICTIONARY_ARTIFACT).hexdigest(),
            _artifact=SCALE_SPECIES_DICTIONARY_ARTIFACT,
        ),
        runtime=dataclasses.replace(
            loader.runtime,
            batch_size=BATCH_SIZE,
            initial_min_source_rows=SCALE_ROWS,
            initial_max_source_rows=SCALE_ROWS,
            statement_timeout_ms=statement_ms,
            total_timeout_seconds=total_seconds,
        ),
    )
    source = dataclasses.replace(
        base.e2e_source_config,
        runtime=dataclasses.replace(
            base.e2e_source_config.runtime,
            batch_size=BATCH_SIZE,
            statement_timeout_ms=statement_ms,
            idle_in_transaction_session_timeout_ms=min(300_000, statement_ms),
            total_timeout_seconds=total_seconds,
        ),
    )
    return loader, source


def _run_loader(
    base: Any,
    *,
    policy: Any,
    absolute_deadline: float,
    measurements: PhaseMeasurements,
    retain_cleanup_debt: bool,
    dictionary: Any,
) -> Any:
    loader_config, source_config = _scale_configs(
        base,
        policy,
        absolute_deadline - time.monotonic(),
    )

    def factory(config: object) -> _MeasuredStore:
        return _MeasuredStore(
            config,
            measurements,
            retain_cleanup_debt=retain_cleanup_debt,
        )

    with patch.object(loader_coordinator, "_target_store_factory", factory):
        return loader_coordinator._run_initial_with_inputs(
            loader_config,
            source_config=source_config,
            source_contract=base.e2e_source_contract,
            columns=source_config.column_map,
            policy=policy,
            dictionary=dictionary,
            species_dictionary_artifact_sha256=(
                loader_config.species_dictionary.expected_raw_sha256
            ),
        )


def _failure_oracle(connection: Any) -> dict[str, int | bool | str]:
    row = connection.execute(
        "SELECT r.status AS release_status, r.cleanup_pending, j.status AS job_status, "
        "j.failure_code, (SELECT count(*) FROM loader_control.notification_outbox AS o "
        "WHERE o.job_id = j.job_id AND o.event_type = 'etl_failed') AS failure_events, "
        "(SELECT count(*) FROM loader_stage.source_inventory AS i "
        "WHERE i.job_id = j.job_id) AS inventory_rows, "
        "(SELECT count(*) FROM loader_stage.disposition_delta AS d "
        "WHERE d.job_id = j.job_id) AS delta_rows, "
        "(SELECT count(*) FROM serve.public_release) AS visible_releases "
        "FROM loader_control.release AS r JOIN loader_control.etl_job AS j "
        "ON j.job_id = r.job_id WHERE r.status = 'failed'"
    ).fetchone()
    expected = {
        "cleanup_pending": True,
        "delta_rows": SCALE_ROWS,
        "failure_code": "LOADER_CANDIDATE_INVALID",
        "failure_events": 1,
        "inventory_rows": SCALE_ROWS,
        "job_status": "failed",
        "release_status": "failed",
        "visible_releases": 0,
    }
    if row != expected:
        raise ScaleAcceptanceError
    return expected


def _visibility_observer(base: Any, measurements: PhaseMeasurements):
    stop = threading.Event()
    state = {"empty": 0, "staged_empty": 0, "complete": 0, "failed": False}
    empty = {
        "releases": 0,
        "species": 0,
        "cells": 0,
        "years": 0,
        "records": 0,
        "cell_total": 0,
        "year_total": 0,
    }
    complete = {
        "releases": 1,
        "species": EXPECTED_COUNTS["species"],
        "cells": EXPECTED_COUNTS["distributionCells"],
        "years": EXPECTED_COUNTS["speciesYears"],
        "records": EXPECTED_COUNTS["publicRecords"],
        "cell_total": EXPECTED_COUNTS["publishedBasis"],
        "year_total": EXPECTED_COUNTS["publishedBasis"],
    }

    def observe() -> None:
        try:
            with base._connection("api") as connection:
                while not stop.wait(0.25):
                    row = connection.execute(
                        "SELECT (SELECT count(*) FROM serve.public_release) AS releases, "
                        "(SELECT count(*) FROM serve.public_species) AS species, "
                        "(SELECT count(*) FROM serve.public_distribution_cell) AS cells, "
                        "(SELECT count(*) FROM serve.public_species_year) AS years, "
                        "(SELECT count(*) FROM serve.public_record) AS records, "
                        "(SELECT COALESCE(sum(record_count), 0) "
                        "FROM serve.public_distribution_cell) AS cell_total, "
                        "(SELECT COALESCE(sum(record_count), 0) "
                        "FROM serve.public_species_year) AS year_total"
                    ).fetchone()
                    if not isinstance(row, dict):
                        state["failed"] = True
                        return
                    if row == empty:
                        state["empty"] += 1
                        if measurements.candidate_staged.is_set():
                            state["staged_empty"] += 1
                        continue
                    if measurements.activation_started.is_set() and row == complete:
                        state["complete"] += 1
                        measurements.complete_observed.set()
                        continue
                    state["failed"] = True
                    return
        except Exception:
            state["failed"] = True

    thread = threading.Thread(target=observe, name="scale-public-visibility", daemon=True)
    thread.start()
    return stop, thread, state


def _success_oracle(connection: Any, report: Any) -> dict[str, Any]:
    manifest = connection.execute(
        "SELECT source_row_count, source_inventory_count, delta_row_count, "
        "eligible_pre_suppression_count, "
        "transform_withheld_count, suppression_withheld_count, published_basis_count, "
        "species_count, cell_count, species_year_count, public_record_count, "
        "candidate_sha256, database_sha256 FROM loader_control.release_manifest "
        "WHERE release_id = %s",
        (report.release_id,),
    ).fetchone()
    expected_manifest = {
        "candidate_sha256": report.candidate_sha256,
        "cell_count": EXPECTED_COUNTS["distributionCells"],
        "database_sha256": report.candidate_sha256,
        "delta_row_count": EXPECTED_COUNTS["sourceRows"],
        "eligible_pre_suppression_count": EXPECTED_COUNTS["eligibleBeforeSuppression"],
        "public_record_count": EXPECTED_COUNTS["publicRecords"],
        "published_basis_count": EXPECTED_COUNTS["publishedBasis"],
        "source_row_count": EXPECTED_COUNTS["sourceRows"],
        "source_inventory_count": EXPECTED_COUNTS["sourceRows"],
        "species_count": EXPECTED_COUNTS["species"],
        "species_year_count": EXPECTED_COUNTS["speciesYears"],
        "suppression_withheld_count": EXPECTED_COUNTS["suppressionWithheld"],
        "transform_withheld_count": EXPECTED_COUNTS["transformWithheld"],
    }
    if manifest != expected_manifest:
        raise ScaleAcceptanceError
    public = connection.execute(
        "SELECT (SELECT count(*) FROM serve.public_release) AS releases, "
        "(SELECT count(*) FROM serve.public_species) AS species, "
        "(SELECT count(*) FROM serve.public_distribution_cell) AS cells, "
        "(SELECT count(*) FROM serve.public_species_year) AS years, "
        "(SELECT count(*) FROM serve.public_record) AS records, "
        "(SELECT COALESCE(sum(record_count), 0) FROM serve.public_distribution_cell) "
        "AS cell_total, (SELECT COALESCE(sum(record_count), 0) "
        "FROM serve.public_species_year) AS year_total"
    ).fetchone()
    expected_public = {
        "cell_total": EXPECTED_COUNTS["publishedBasis"],
        "cells": EXPECTED_COUNTS["distributionCells"],
        "records": 0,
        "releases": 1,
        "species": EXPECTED_COUNTS["species"],
        "year_total": EXPECTED_COUNTS["publishedBasis"],
        "years": EXPECTED_COUNTS["speciesYears"],
    }
    if public != expected_public:
        raise ScaleAcceptanceError
    safety = connection.execute(
        "SELECT "
        "min(record_precision_metres) FILTER (WHERE species_id = 'SYNTH-SCALE-SENS') "
        "AS sensitive_min_precision, "
        "max(record_precision_metres) FILTER (WHERE species_id = 'SYNTH-SCALE-ORDINARY') "
        "AS ordinary_max_precision, "
        "count(*) FILTER (WHERE species_id = 'SYNTH-SCALE-SPARSE') AS sparse_ledger, "
        # Literal percent signs must be doubled: this query binds a parameter,
        # and psycopg treats a single % as a placeholder introducer ('%P' is
        # rejected outright, which aborted the whole acceptance run after a
        # successful activation).
        "count(*) FILTER (WHERE coalesce(place, '') LIKE '%%PRIVATE-SCALE%%' "
        "OR coalesce(source_label, '') LIKE '%%PRIVATE-SCALE%%') AS private_text, "
        "count(*) FILTER (WHERE place IS NOT NULL) AS published_place_values, "
        "count(*) FILTER (WHERE abundance IS NOT NULL) AS published_abundance_values, "
        "count(*) FILTER (WHERE record_type IS NOT NULL) AS published_record_types, "
        "count(*) FILTER (WHERE verified_status IS NOT NULL) AS published_verification, "
        "count(*) FILTER (WHERE disposition IN ('eligible', 'suppressed') AND NOT ("
        "(min_easting, min_northing, max_easting, max_northing) "
        "IN ((358000, 172000, 359000, 173000), "
        "(359000, 172000, 360000, 173000)))) AS invalid_safe_bounds, "
        "count(*) AS ledger_rows FROM loader_control.source_disposition "
        "WHERE release_id = %s",
        (report.release_id,),
    ).fetchone()
    expected_safety = {
        "ledger_rows": SCALE_ROWS,
        "ordinary_max_precision": 100,
        "private_text": 0,
        "published_abundance_values": 0,
        "published_place_values": 0,
        "published_record_types": 0,
        "published_verification": 0,
        "invalid_safe_bounds": 0,
        "sensitive_min_precision": 1_000,
        "sparse_ledger": 2,
    }
    if safety != expected_safety:
        raise ScaleAcceptanceError
    forbidden_columns = connection.execute(
        "SELECT table_schema, table_name, column_name FROM information_schema.columns "
        "WHERE table_schema IN ('loader_control', 'loader_stage', 'publication', 'serve') "
        "AND column_name IN ('comments', 'easting', 'northing', 'sensitive', 'unique_no') "
        "ORDER BY table_schema, table_name, column_name"
    ).fetchall()
    if forbidden_columns:
        raise ScaleAcceptanceError
    capabilities = connection.execute(
        "SELECT verification_available, individual_records_available, "
        "record_verification_available, place_available, abundance_available, "
        "record_type_available FROM serve.public_release"
    ).fetchone()
    if capabilities != {
        "abundance_available": False,
        "individual_records_available": False,
        "place_available": False,
        "record_type_available": False,
        "record_verification_available": False,
        "verification_available": False,
    }:
        raise ScaleAcceptanceError
    withheld = connection.execute(
        "SELECT reason_code, row_count FROM loader_control.withheld_summary "
        "WHERE release_id = %s ORDER BY reason_code",
        (report.release_id,),
    ).fetchall()
    if withheld != [
        {"reason_code": "licence-not-permitted", "row_count": 1},
        {"reason_code": "suppressed-sparse-cell", "row_count": 2},
    ]:
        raise ScaleAcceptanceError
    lifecycle = connection.execute(
        "SELECT r.status AS release_status, r.cleanup_pending, j.status AS job_status, "
        "(SELECT count(*) FROM loader_control.notification_outbox AS o "
        "WHERE o.job_id = j.job_id AND o.event_type = 'etl_succeeded') AS success_events, "
        "(SELECT count(*) FROM loader_stage.source_inventory) AS inventory_rows, "
        "(SELECT count(*) FROM loader_stage.disposition_delta) AS delta_rows, "
        "(SELECT count(*) FROM loader_stage.reconciliation_result) AS check_rows, "
        "(SELECT count(*) FROM loader_control.release WHERE status = 'failed' "
        "AND cleanup_pending) AS pending_failures, "
        "(SELECT count(*) FROM loader_control.release WHERE status = 'failed') "
        "AS failed_releases, "
        "(SELECT count(*) FROM loader_control.etl_job WHERE status = 'failed' "
        "AND failure_code = 'LOADER_CANDIDATE_INVALID') AS failed_jobs, "
        "(SELECT count(*) FROM loader_control.notification_outbox AS o "
        "JOIN loader_control.etl_job AS failed_job ON failed_job.job_id = o.job_id "
        "WHERE failed_job.status = 'failed' AND o.event_type = 'etl_failed') "
        "AS retained_failure_events, "
        "(SELECT count(*) FROM loader_control.source_disposition AS d "
        "JOIN loader_control.release AS failed ON failed.release_id = d.release_id "
        "WHERE failed.status = 'failed') AS failed_ledger_rows, "
        "(SELECT count(*) FROM publication.public_release AS p "
        "JOIN loader_control.release AS failed ON failed.release_id = p.release_id "
        "WHERE failed.status = 'failed') AS failed_public_release_rows, "
        "(SELECT count(*) FROM publication.public_species AS p "
        "JOIN loader_control.release AS failed ON failed.release_id = p.release_id "
        "WHERE failed.status = 'failed') AS failed_species_rows, "
        "(SELECT count(*) FROM publication.public_distribution_cell AS p "
        "JOIN loader_control.release AS failed ON failed.release_id = p.release_id "
        "WHERE failed.status = 'failed') AS failed_cell_rows, "
        "(SELECT count(*) FROM publication.public_species_year AS p "
        "JOIN loader_control.release AS failed ON failed.release_id = p.release_id "
        "WHERE failed.status = 'failed') AS failed_year_rows, "
        "(SELECT count(*) FROM publication.public_record AS p "
        "JOIN loader_control.release AS failed ON failed.release_id = p.release_id "
        "WHERE failed.status = 'failed') AS failed_record_rows "
        "FROM loader_control.release AS r JOIN loader_control.etl_job AS j "
        "ON j.job_id = r.job_id WHERE r.release_id = %s",
        (report.release_id,),
    ).fetchone()
    expected_lifecycle = {
        "check_rows": 0,
        "cleanup_pending": False,
        "delta_rows": 0,
        "failed_cell_rows": 0,
        "failed_jobs": 1,
        "failed_ledger_rows": 0,
        "failed_public_release_rows": 0,
        "failed_record_rows": 0,
        "failed_releases": 1,
        "failed_species_rows": 0,
        "failed_year_rows": 0,
        "inventory_rows": 0,
        "job_status": "succeeded",
        "pending_failures": 0,
        "release_status": "active",
        "retained_failure_events": 1,
        "success_events": 1,
    }
    if lifecycle != expected_lifecycle:
        raise ScaleAcceptanceError
    return {
        "candidateDigestMatchesDatabase": True,
        "cleanupDebtCleared": True,
        "countsMatchIndependentFixture": True,
        "licenceWithholding": True,
        "optionalAndRowFieldsDisabled": True,
        "privateSourceColumnsAbsent": True,
        "privateSentinelsAbsent": True,
        "sensitivePrecisionAtLeast1000m": True,
        "sparseCohortSuppressed": True,
        "stageEmptyAfterActivation": True,
    }


def _manifest_digests(connection: Any, release_id: object) -> dict[str, str]:
    row = connection.execute(
        "SELECT source_contract_sha256, observed_view_definition_sha256, "
        "observed_view_identity_sha256, projection_sha256, publication_policy_sha256, "
        "policy_approval_sha256, compatibility_sha256, species_dictionary_sha256, "
        "species_dictionary_artifact_sha256, "
        "sensitivity_snapshot_sha256, source_result_sha256, candidate_sha256, "
        "database_sha256 FROM loader_control.release_manifest WHERE release_id = %s",
        (release_id,),
    ).fetchone()
    if not isinstance(row, dict) or set(row) != {
        "candidate_sha256",
        "compatibility_sha256",
        "database_sha256",
        "observed_view_definition_sha256",
        "observed_view_identity_sha256",
        "policy_approval_sha256",
        "projection_sha256",
        "publication_policy_sha256",
        "sensitivity_snapshot_sha256",
        "source_contract_sha256",
        "source_result_sha256",
        "species_dictionary_artifact_sha256",
        "species_dictionary_sha256",
    }:
        raise ScaleAcceptanceError
    result: dict[str, str] = {}
    for key, value in row.items():
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ScaleAcceptanceError
        else:
            result[key] = value
    if result["candidate_sha256"] != result["database_sha256"]:
        raise ScaleAcceptanceError
    return result


def _raw_mib(value: int | float) -> float:
    return float(value) / (1024 * 1024)


def _require_budget(observed: float, allowed: float) -> None:
    if not math.isfinite(observed) or observed < 0 or observed > allowed:
        raise ScaleAcceptanceError


def _write_evidence(path: Path, document: dict[str, Any]) -> str:
    rendered = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    return rendered


def run(evidence_path: Path, budgets: Budgets) -> dict[str, Any]:
    if os.environ.get("BRERC_LOADER_SCALE_ACCEPTANCE") != CONFIRMATION:
        raise ScaleAcceptanceError
    for required in (SCALE_FIXTURE, MIGRATION, ROLES_SQL, WORKFLOW, Path(__file__).resolve()):
        if not required.is_file():
            raise ScaleAcceptanceError
    commit, clean = _git_identity()
    if not clean:
        raise ScaleAcceptanceError
    free_before = shutil.disk_usage(evidence_path.parent).free
    if _raw_mib(free_before) < budgets.min_free_disk_mib:
        raise ScaleAcceptanceError

    integration = TestPostGIS16DestinationIntegration(methodName="runTest")
    integration.setUpClass()
    with integration._admin_connection() as target_admin:
        target_admin.execute("TRUNCATE TABLE loader_control.source_state CASCADE")
    with integration._source_admin_connection() as source_admin:
        source_counts = _source_oracle(source_admin)
        source_durability = _durability(source_admin, postgis=False)
        _reset_statistics(source_admin)
        source_before = _snapshot(source_admin)
    with integration._admin_connection() as target_admin:
        target_durability = _durability(target_admin, postgis=True)
        unlogged = target_admin.execute(
            "SELECT count(*) AS n FROM pg_class AS c JOIN pg_namespace AS n "
            "ON n.oid = c.relnamespace WHERE n.nspname IN "
            "('loader_control', 'loader_stage', 'publication') "
            "AND c.relkind IN ('r', 'p') AND c.relpersistence <> 'p'"
        ).fetchone()
        if unlogged != {"n": 0}:
            raise ScaleAcceptanceError
        _reset_statistics(target_admin)
        target_before = _snapshot(target_admin)

    workload_started = time.monotonic()
    workload_deadline = workload_started + budgets.total_seconds
    failure_measurements = PhaseMeasurements()
    success_measurements = PhaseMeasurements()
    dictionary = _scale_species_dictionary()
    failure_policy = _scale_policy(
        dictionary=dictionary,
        allowed_licence_values=frozenset({"z"}),
    )
    success_policy = _scale_policy(
        dictionary=dictionary,
        allowed_licence_values=frozenset({"y"}),
    )
    with _sample_resources(integration, evidence_path, target_before) as resource_measurements:
        failure_started = time.monotonic()
        try:
            _run_loader(
                integration,
                policy=failure_policy,
                absolute_deadline=workload_deadline,
                measurements=failure_measurements,
                retain_cleanup_debt=True,
                dictionary=dictionary,
            )
        except LoaderCandidateInvalid:
            pass
        except LoaderError:
            raise ScaleAcceptanceError from None
        else:
            raise ScaleAcceptanceError
        failure_seconds = time.monotonic() - failure_started
        with integration._admin_connection() as target_admin:
            failure_state = _failure_oracle(target_admin)

        stop, observer, visibility = _visibility_observer(integration, success_measurements)
        success_started = time.monotonic()
        try:
            report = _run_loader(
                integration,
                policy=success_policy,
                absolute_deadline=workload_deadline,
                measurements=success_measurements,
                retain_cleanup_debt=False,
                dictionary=dictionary,
            )
            if not success_measurements.complete_observed.wait(timeout=10):
                raise ScaleAcceptanceError
        finally:
            stop.set()
            observer.join(timeout=10)
        success_seconds = time.monotonic() - success_started
        if (
            observer.is_alive()
            or visibility["failed"]
            or visibility["empty"] < 1
            or visibility["staged_empty"] < 1
            or visibility["complete"] < 1
        ):
            raise ScaleAcceptanceError
        if report.source_rows != SCALE_ROWS or not report.activated:
            raise ScaleAcceptanceError
        expected_batches = [BATCH_SIZE] * (SCALE_ROWS // BATCH_SIZE)
        if (
            failure_measurements.stage_batch_sizes != expected_batches
            or success_measurements.stage_batch_sizes != expected_batches
        ):
            raise ScaleAcceptanceError

        with integration._admin_connection() as target_admin:
            final_oracles = _success_oracle(target_admin, report)
            manifest_digests = _manifest_digests(target_admin, report.release_id)
            target_after = _snapshot(target_admin)
            target_wal_bytes = _wal_bytes(
                target_admin,
                target_before.wal_lsn,
                target_after.wal_lsn,
            )
        with integration._source_admin_connection() as source_admin:
            source_after = _snapshot(source_admin)

    total_seconds = time.monotonic() - workload_started

    finalize_seconds = max(
        (*failure_measurements.finalize_seconds, *success_measurements.finalize_seconds),
        default=-1.0,
    )
    activate_seconds = max(success_measurements.activate_seconds, default=-1.0)
    cleanup_seconds = max(success_measurements.cleanup_seconds, default=-1.0)
    free_after = shutil.disk_usage(evidence_path.parent).free
    raw_metrics = {
        "activateSeconds": activate_seconds,
        "cleanupSeconds": cleanup_seconds,
        "failureRunSeconds": failure_seconds,
        "finalizeSeconds": finalize_seconds,
        "freeDiskAfterMiB": _raw_mib(free_after),
        "freeDiskBeforeMiB": _raw_mib(free_before),
        "minimumSampledFreeDiskMiB": _raw_mib(
            min(free_before, resource_measurements.minimum_free_disk_bytes, free_after)
        ),
        "processPeakRssMiB": _rss_mib(),
        "resourceSamples": float(resource_measurements.samples),
        "sourceTempMiB": _raw_mib(source_after.temp_bytes - source_before.temp_bytes),
        "successRunSeconds": success_seconds,
        "targetDatabaseSampledPeakGrowthMiB": _raw_mib(
            max(
                0,
                resource_measurements.target_database_peak_bytes - target_before.database_bytes,
                target_after.database_bytes - target_before.database_bytes,
            )
        ),
        "targetTempMiB": _raw_mib(target_after.temp_bytes - target_before.temp_bytes),
        "targetWalMiB": _raw_mib(target_wal_bytes),
        "totalSeconds": total_seconds,
    }
    for observed, allowed in (
        (raw_metrics["activateSeconds"], budgets.activate_seconds),
        (raw_metrics["cleanupSeconds"], budgets.cleanup_seconds),
        (raw_metrics["finalizeSeconds"], budgets.finalize_seconds),
        (raw_metrics["processPeakRssMiB"], budgets.rss_mib),
        (raw_metrics["sourceTempMiB"], budgets.source_temp_mib),
        (
            raw_metrics["targetDatabaseSampledPeakGrowthMiB"],
            budgets.target_db_growth_mib,
        ),
        (raw_metrics["targetTempMiB"], budgets.target_temp_mib),
        (raw_metrics["targetWalMiB"], budgets.target_wal_mib),
        (raw_metrics["totalSeconds"], budgets.total_seconds),
    ):
        _require_budget(observed, allowed)
    if raw_metrics["minimumSampledFreeDiskMiB"] < budgets.min_free_disk_mib:
        raise ScaleAcceptanceError
    metrics = {key: round(value, 3) for key, value in raw_metrics.items()}

    files = {
        "migration": _sha256(MIGRATION),
        "roles": _sha256(ROLES_SQL),
        "runner": _sha256(Path(__file__).resolve()),
        "sourceGenerator": _sha256(SCALE_FIXTURE),
        "workflow": _sha256(WORKFLOW),
    }
    oracles = {
        **final_oracles,
        "candidateInvisibleBeforeActivation": visibility["staged_empty"] > 0,
        "durableFailureBeforeCleanup": failure_state["cleanup_pending"] is True,
        "exactFiveMillionSourceRows": source_counts["rows"] == SCALE_ROWS,
        "fixedFiveThousandRowBatchesObserved": (
            len(failure_measurements.stage_batch_sizes) == SCALE_ROWS // BATCH_SIZE
            and len(success_measurements.stage_batch_sizes) == SCALE_ROWS // BATCH_SIZE
        ),
        "initialOnlyReplacementNotApplicable": True,
        "noUnloggedTargetTables": True,
        "observerSawCompleteState": visibility["complete"] > 0,
        "observerSawEmptyState": visibility["empty"] > 0,
    }
    if not all(oracles.values()):
        raise ScaleAcceptanceError
    return {
        "budgets": budgets.as_document(),
        "counts": EXPECTED_COUNTS,
        "durability": {"source": source_durability, "target": target_durability},
        "evidenceVersion": EVIDENCE_VERSION,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "metrics": metrics,
        "oracles": oracles,
        "reproducibility": {
            "batchSize": BATCH_SIZE,
            "filesSha256": files,
            "gitCommit": commit,
            "manifestDigests": manifest_digests,
            "runnerCapacity": _runner_capacity(),
            "sourceImage": SOURCE_IMAGE,
            "syntheticGeneratorRows": SCALE_ROWS,
            "targetImage": TARGET_IMAGE,
            "workingTreeClean": clean,
        },
        "scope": {
            "data": "synthetic-only",
            "environment": "acceptance-hardware-not-production",
            "mode": "initial-empty-to-complete",
            "replacementAtomicity": "not-applicable-in-initial-mode",
            "setupAndGenerationExcludedFromLoaderTiming": True,
        },
        "status": "passed",
    }


def main(argv: Sequence[str] | None = None) -> int:
    evidence_path: Path | None = None
    try:
        evidence_path, budgets = _arguments(sys.argv[1:] if argv is None else argv)
        document = run(evidence_path, budgets)
        rendered = _write_evidence(evidence_path, document)
        print(rendered)
        return 0
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        failure = json.dumps(
            {"code": "SCALE_ACCEPTANCE_INTERRUPTED", "status": "failed"},
            sort_keys=True,
            separators=(",", ":"),
        )
    except KeyboardInterrupt:
        failure = json.dumps(
            {"code": "SCALE_ACCEPTANCE_INTERRUPTED", "status": "failed"},
            sort_keys=True,
            separators=(",", ":"),
        )
    except Exception:
        failure = json.dumps(
            {"code": "SCALE_ACCEPTANCE_FAILED", "status": "failed"},
            sort_keys=True,
            separators=(",", ":"),
        )
    if evidence_path is not None:
        with suppress(Exception):
            _write_evidence(evidence_path, json.loads(failure))
    print(failure)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
