"""Orchestration tests for the PostgreSQL release coordinator.

These tests use lifecycle-level fakes deliberately.  The coordinator tests
prove ordering, bounded batching, redaction and atomic-publication behaviour;
the PostgreSQL integration suite proves the concrete SQL and PostGIS schema.
No fake in this module is allowed to accept a raw BRERC row.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import unittest
from pathlib import Path
from unittest import mock
from uuid import UUID

from brerc_loader.config import (
    LOADER_CONFIG_VERSION,
    LoaderConfig,
    LoaderRuntimeConfig,
    PublicationConfig,
    ReconciliationConfig,
    SpeciesDictionaryConfig,
    TargetConnectionConfig,
)
from brerc_loader.errors import (
    IncrementalSourceContractBlocked,
    LoaderAlreadyRunning,
    LoaderCandidateInvalid,
    LoaderExecutionFailed,
    LoaderPolicyInvalid,
    LoaderReleaseBlocked,
    LoaderSourceCountRejected,
)
from brerc_loader.models import LoadMode
from brerc_source.models import SafeSourceSnapshotEvidence
from connector_tests.test_postgres_connector import (
    CONNECTOR_DICTIONARY,
    FakeConnection,
    approved_contract,
    approved_policy,
    connector_config,
    source_row,
)
from etl.contract import PublicRecord
from etl.species import SpeciesDictionary
from etl.streaming import SafeDisposition

SOURCE_ID = "dashboard.main_data_dash"
OLD_RELEASE_ID = "00000000-0000-4000-8000-000000000001"
RAW_SENTINELS = (
    "RAW-UNIQUE-001",
    "ST58721721",
    "358712.34",
    "172145.67",
    "private garden address",
    "recorder full name",
    "sensitive=yes",
)
SPECIES_DICTIONARY_ARTIFACT = (
    b"SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE\n"
    b"5088,Anguis fragilis,Slow-worm,No\n"
    b"SYNTH-1,Synthetic species alpha,Synthetic alpha,No\n"
    b"SYNTH-2,Synthetic species beta,Synthetic beta,Yes\n"
)
SPECIES_DICTIONARY_ARTIFACT_SHA256 = hashlib.sha256(SPECIES_DICTIONARY_ARTIFACT).hexdigest()


def loader_config(*, minimum: int = 1, maximum: int = 100) -> LoaderConfig:
    """Construct a fully validated, filesystem-independent test config."""
    runtime = LoaderRuntimeConfig(
        expected_target_database="brerc_ui_test",
        expected_target_environment_id=UUID("11111111-1111-4111-8111-111111111111"),
        expected_target_role="brerc_release_loader_test",
        batch_size=100,
        initial_min_source_rows=minimum,
        initial_max_source_rows=maximum,
        connect_timeout_seconds=5,
        lock_timeout_ms=1_000,
        statement_timeout_ms=60_000,
        total_timeout_seconds=300,
    )
    artifact = b'{"synthetic":"coordinator-test"}\n'
    return LoaderConfig(
        version=LOADER_CONFIG_VERSION,
        source_config_path=Path("/controlled/source.yaml"),
        publication=PublicationConfig(
            policy_path=Path("/controlled/publication-policy.json"),
            expected_sha256=hashlib.sha256(artifact).hexdigest(),
            public_id_secret_env="BRERC_PUBLIC_ID_TEST_SECRET",  # noqa: S106 - env name
            _artifact=artifact,
            _public_id_secret=b"public-id-test-secret-material-32bytes",
        ),
        species_dictionary=SpeciesDictionaryConfig(
            csv_path=Path("/controlled/species-dictionary.csv"),
            expected_raw_sha256=SPECIES_DICTIONARY_ARTIFACT_SHA256,
            _artifact=SPECIES_DICTIONARY_ARTIFACT,
        ),
        runtime=runtime,
        target_connection=TargetConnectionConfig(
            mode="direct",
            sslmode="verify-full",
            connect_timeout_seconds=runtime.connect_timeout_seconds,
            _resolved_parameters=(
                ("passfile", "/controlled/target.pgpass"),
                ("sslrootcert", "/controlled/target-root.crt"),
                ("sslmode", "verify-full"),
                ("application_name", "brerc-dashboard-release-loader"),
                ("connect_timeout", runtime.connect_timeout_seconds),
                ("host", "target.example.test"),
                ("port", 5432),
                ("dbname", "brerc_ui_test"),
                ("user", "brerc_release_loader_test"),
            ),
        ),
        reconciliation=ReconciliationConfig(
            secret_env="BRERC_RECONCILIATION_TEST_SECRET",  # noqa: S106 - env name
            _secret=b"reconciliation-test-secret-material-32bytes",
        ),
    )


def minimum_count_policy(threshold: int = 3):
    """Return a freshly approval-bound synthetic minimum-count policy."""
    policy = dataclasses.replace(
        approved_policy(),
        suppression_mode="minimum-count",
        min_records_per_cell=threshold,
        approval_digest=None,
    )
    policy = dataclasses.replace(
        policy,
        approval_digest=policy._expected_approval_digest(),
    )
    policy.validate()
    policy.assert_approved()
    return policy


def approved_artifact_config() -> LoaderConfig:
    """Config whose policy artifact passes before the real-view release gate."""
    policy = approved_policy()
    artifact = json.dumps(
        policy.approval_artifact(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    base = loader_config()
    return dataclasses.replace(
        base,
        publication=PublicationConfig(
            policy_path=Path("/controlled/approved-policy.json"),
            expected_sha256=hashlib.sha256(artifact).hexdigest(),
            public_id_secret_env="BRERC_PUBLIC_ID_TEST_SECRET",  # noqa: S106 - env name
            _artifact=artifact,
            _public_id_secret=policy.public_id_salt.encode("utf-8"),
        ),
    )


def disposition(
    number: int,
    *,
    species_id: str = "5088",
    year: int = 2024,
    cell_id: str = "ST5872",
) -> SafeDisposition:
    """Build one safe post-transform disposition; no raw source value appears."""
    token = hashlib.sha256(f"token:{number}".encode()).hexdigest()
    fingerprint = hashlib.sha256(f"fingerprint:{number}".encode()).hexdigest()
    record = PublicRecord(
        record_id=hashlib.sha256(f"public:{number}".encode()).hexdigest()[:32],
        species_id=species_id,
        scientific_name="Anguis fragilis",
        common_name="Slow-worm",
        grid_ref="ST587721",
        precision_metres=100,
        place=None,
        year=year,
        abundance=None,
        record_type=None,
        verified="unknown",
        source="BRERC",
    )
    return SafeDisposition(
        source_token=token,
        source_fingerprint=fingerprint,
        record=record,
        withheld_reason=None,
        cell_id=cell_id,
        cell_precision_metres=1_000,
        min_easting=358_000,
        min_northing=172_000,
        max_easting=359_000,
        max_northing=173_000,
    )


def withheld_disposition(number: int) -> SafeDisposition:
    return SafeDisposition(
        source_token=hashlib.sha256(f"token:{number}".encode()).hexdigest(),
        source_fingerprint=hashlib.sha256(f"fingerprint:{number}".encode()).hexdigest(),
        record=None,
        withheld_reason="licence-not-approved",
        cell_id=None,
        cell_precision_metres=None,
        min_easting=None,
        min_northing=None,
        max_easting=None,
        max_northing=None,
    )


def evidence(
    row_count: int,
    *,
    eligible: int | None = None,
    withheld: int = 0,
) -> SafeSourceSnapshotEvidence:
    if eligible is None:
        eligible = row_count - withheld
    return SafeSourceSnapshotEvidence(
        captured_at_utc="2026-08-14T12:00:00.000000Z",
        contract_version="connector-test-source-v1",
        contract_sha256="a" * 64,
        policy_version="connector-test-policy",
        policy_approval_digest="b" * 64,
        observed_species_dictionary_sha256=CONNECTOR_DICTIONARY.digest(),
        observed_definition_sha256="c" * 64,
        observed_identity_sha256="d" * 64,
        result_columns=("unique_no", "species_no"),
        rows_seen=row_count,
        records_eligible_before_suppression=eligible,
        withheld_by_reason=((("licence-not-approved", withheld),) if withheld else ()),
        sensitivity_buckets=(("no", row_count),),
    )


class FakeSafeSnapshot:
    """A one-shot source snapshot that exposes evidence only after exhaustion."""

    def __init__(
        self,
        batches: list[tuple[SafeDisposition, ...]],
        *,
        fail_after_batches: int | None = None,
    ) -> None:
        self.batches = batches
        self.fail_after_batches = fail_after_batches
        self.entered = False
        self.closed = False
        self.exhausted = False
        self.index = 0
        rows = [item for batch in batches for item in batch]
        withheld = sum(item.record is None for item in rows)
        self._evidence = evidence(len(rows), withheld=withheld)

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, _type, _value, _traceback):
        self.closed = True
        return False

    def __iter__(self):
        return self

    def __next__(self):
        if self.fail_after_batches is not None and self.index == self.fail_after_batches:
            raise RuntimeError("RAW-UNIQUE-001 at private source host")
        if self.index >= len(self.batches):
            self.exhausted = True
            raise StopIteration
        batch = self.batches[self.index]
        self.index += 1
        return batch

    @property
    def evidence(self) -> SafeSourceSnapshotEvidence:
        if not self.exhausted:
            raise AssertionError("evidence was read before the source snapshot was exhausted")
        return self._evidence


class FakeSourceConnector:
    def __init__(self, snapshot: FakeSafeSnapshot) -> None:
        self.snapshot = snapshot
        self.open_calls: list[dict[str, object]] = []

    def _open_safe_initial_snapshot(self, **kwargs):
        self.open_calls.append(kwargs)
        return self.snapshot


def _walk_strings(value: object):
    if isinstance(value, str):
        yield value
    elif dataclasses.is_dataclass(value):
        for field in dataclasses.fields(value):
            yield from _walk_strings(getattr(value, field.name))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            yield from _walk_strings(item)


class FakeTargetStore:
    """Lifecycle fake with an atomic active pointer and privacy tripwire."""

    def __init__(
        self,
        coordinator_module: object,
        *,
        active_release: str | None = None,
        lock_failure: BaseException | None = None,
        stage_failure_at: int | None = None,
        maximum_batch_size: int = 100,
        begin_failure_after_commit: bool = False,
        close_failure: BaseException | None = None,
    ) -> None:
        self.module = coordinator_module
        self.active_release = active_release
        self.lock_failure = lock_failure
        self.stage_failure_at = stage_failure_at
        self.maximum_batch_size = maximum_batch_size
        self.begin_failure_after_commit = begin_failure_after_commit
        self.close_failure = close_failure
        self.calls: list[str] = []
        self.staged: list[SafeDisposition] = []
        self.stage_sizes: list[int] = []
        self.seen_tokens: set[str] = set()
        self.closed = False
        self.activated = False
        self.failed_codes: list[str] = []
        self.cancelled = 0
        self.finalize_seen_count: int | None = None
        self.finalize_kwargs: dict[str, object] | None = None
        self.published_after_suppression: list[SafeDisposition] = []
        self.open_candidate = False

    def acquire(self, source_id: str) -> None:
        self.calls.append("acquire")
        self.assert_private(source_id)
        if self.lock_failure is not None:
            raise self.lock_failure

    def begin_initial(self, source_id: str, attempt: object):
        self.calls.append("begin_initial")
        self._assert_source(source_id)
        if not isinstance(attempt, self.module._CandidateHandle):
            raise AssertionError("coordinator did not retain a typed attempt handle")
        self.open_candidate = True
        if self.begin_failure_after_commit:
            raise RuntimeError("COMMIT succeeded but private connection acknowledgement was lost")
        return dataclasses.replace(
            attempt,
            base_release_id=(
                None if self.active_release is None else self.module.UUID(self.active_release)
            ),
        )

    def stage_batch(self, _handle: object, batch: tuple[SafeDisposition, ...]) -> None:
        self.calls.append("stage_batch")
        self.stage_sizes.append(len(batch))
        self.assert_private(batch)
        if len(batch) > self.maximum_batch_size:
            raise LoaderCandidateInvalid()
        if self.stage_failure_at is not None and len(self.stage_sizes) == self.stage_failure_at:
            raise RuntimeError("private garden address in failed INSERT")
        for item in batch:
            if item.source_token in self.seen_tokens:
                raise LoaderCandidateInvalid()
            self.seen_tokens.add(item.source_token)
            self.staged.append(item)

    def finalize(
        self,
        _handle: object,
        *,
        evidence: object,
        policy: object,
        **kwargs: object,
    ):
        self.calls.append("finalize")
        self.assert_private(evidence)
        self.finalize_kwargs = kwargs
        self.finalize_seen_count = len(self.staged)
        counts: dict[tuple[object, ...], int] = {}
        for item in self.staged:
            if item.record is None:
                continue
            cohort = (
                item.record.species_id,
                item.record.year,
                item.cell_id,
                item.cell_precision_metres,
            )
            counts[cohort] = counts.get(cohort, 0) + 1
        threshold = policy.min_records_per_cell
        self.published_after_suppression = [
            item
            for item in self.staged
            if item.record is not None
            and counts[
                (
                    item.record.species_id,
                    item.record.year,
                    item.cell_id,
                    item.cell_precision_metres,
                )
            ]
            >= threshold
        ]
        return self.module._CandidateSummary(
            source_rows=evidence.rows_seen,
            published_records=(
                len(self.published_after_suppression) if policy.publish_individual_records else 0
            ),
            distribution_cells=len(
                {
                    (
                        item.record.species_id,
                        item.record.year,
                        item.cell_id,
                        item.cell_precision_metres,
                    )
                    for item in self.published_after_suppression
                    if item.record is not None
                }
            ),
            candidate_sha256="e" * 64,
        )

    def activate(self, handle: object, summary: object):
        self.calls.append("activate")
        self.active_release = handle.release_id
        self.activated = True
        self.open_candidate = False
        return self.module._ActivationResult(
            run_id=handle.job_id,
            release_id=handle.release_id,
            source_rows=summary.source_rows,
            published_records=summary.published_records,
            distribution_cells=summary.distribution_cells,
            candidate_sha256=summary.candidate_sha256,
        )

    def fail(self, _handle: object, fixed_code: str) -> None:
        self.calls.append("fail")
        self.failed_codes.append(fixed_code)
        self.assert_private(fixed_code)
        self.open_candidate = False

    def cancel(self) -> None:
        self.calls.append("cancel")
        self.cancelled += 1

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True
        if self.close_failure is not None:
            raise self.close_failure

    def assert_private(self, value: object) -> None:
        rendered = " ".join(_walk_strings(value))
        for sentinel in RAW_SENTINELS:
            if sentinel in rendered:
                raise AssertionError("raw source value crossed the target boundary")

    @staticmethod
    def _assert_source(source_id: str) -> None:
        if source_id != SOURCE_ID:
            raise AssertionError("coordinator used an unexpected source identity")


class CoordinatorCase(unittest.TestCase):
    """Shared factory patching once the production coordinator is imported."""

    @classmethod
    def setUpClass(cls) -> None:
        from brerc_loader import postgres as coordinator

        cls.coordinator = coordinator

    def run_initial(
        self,
        batches: list[tuple[SafeDisposition, ...]],
        *,
        config: LoaderConfig | None = None,
        policy: object | None = None,
        target: FakeTargetStore | None = None,
        fail_after_batches: int | None = None,
        source_batch_size: int | None = None,
        dictionary: SpeciesDictionary | None = CONNECTOR_DICTIONARY,
        species_dictionary_artifact_sha256: str = SPECIES_DICTIONARY_ARTIFACT_SHA256,
        observed_dictionary_sha256: str | None = None,
    ):
        contract = approved_contract()
        source_config = connector_config(contract)
        if source_batch_size is not None:
            source_config = dataclasses.replace(
                source_config,
                runtime=dataclasses.replace(
                    source_config.runtime,
                    batch_size=source_batch_size,
                ),
            )
        snapshot = FakeSafeSnapshot(batches, fail_after_batches=fail_after_batches)
        if observed_dictionary_sha256 is not None:
            snapshot._evidence = dataclasses.replace(
                snapshot._evidence,
                observed_species_dictionary_sha256=observed_dictionary_sha256,
            )
        source = FakeSourceConnector(snapshot)
        if target is None:
            target = FakeTargetStore(self.coordinator)
        self.last_source = source
        self.last_snapshot = snapshot
        self.last_target = target
        with (
            mock.patch.object(
                self.coordinator,
                "_source_connector_factory",
                return_value=source,
            ),
            mock.patch.object(
                self.coordinator,
                "_target_store_factory",
                return_value=target,
            ),
        ):
            report = self.coordinator._run_initial_with_inputs(
                loader_config() if config is None else config,
                source_config=source_config,
                source_contract=contract,
                columns=source_config.column_map,
                policy=approved_policy() if policy is None else policy,
                dictionary=dictionary,
                species_dictionary_artifact_sha256=(species_dictionary_artifact_sha256),
            )
        return report, source, snapshot, target


class TestPreSocketGates(CoordinatorCase):
    def test_direct_incremental_call_is_blocked_before_any_adapter_factory(self) -> None:
        source_factory = mock.Mock(side_effect=AssertionError("source socket opened"))
        target_factory = mock.Mock(side_effect=AssertionError("target socket opened"))
        with (
            mock.patch.object(self.coordinator, "_source_connector_factory", source_factory),
            mock.patch.object(
                self.coordinator,
                "_target_store_factory",
                target_factory,
            ),
            self.assertRaises(IncrementalSourceContractBlocked),
        ):
            self.coordinator.run_load(loader_config(), LoadMode.INCREMENTAL)
        source_factory.assert_not_called()
        target_factory.assert_not_called()

    def test_current_unapproved_brerc_view_blocks_initial_before_config_or_sockets(self) -> None:
        source_config_loader = mock.Mock(side_effect=AssertionError("source config was read"))
        source_factory = mock.Mock(side_effect=AssertionError("source socket opened"))
        target_factory = mock.Mock(side_effect=AssertionError("target socket opened"))
        with (
            mock.patch.object(
                self.coordinator,
                "load_source_config",
                source_config_loader,
            ),
            mock.patch.object(self.coordinator, "_source_connector_factory", source_factory),
            mock.patch.object(
                self.coordinator,
                "_target_store_factory",
                target_factory,
            ),
            self.assertRaises(LoaderReleaseBlocked),
        ):
            self.coordinator.run_load(approved_artifact_config(), LoadMode.INITIAL)
        source_config_loader.assert_not_called()
        source_factory.assert_not_called()
        target_factory.assert_not_called()

    def test_dictionary_binding_failures_stop_before_both_adapter_factories(self) -> None:
        contract = approved_contract()
        source_config = connector_config(contract)
        mismatched = SpeciesDictionary.from_rows(
            [
                {
                    "SPECIES_NO": "OTHER-1",
                    "SCIENTIFIC": "Different species",
                    "COMMON_NAM": "Different",
                    "SENSITIVE": "No",
                }
            ]
        )
        cases = (
            ("missing", None, SPECIES_DICTIONARY_ARTIFACT_SHA256),
            ("semantic-mismatch", mismatched, SPECIES_DICTIONARY_ARTIFACT_SHA256),
            ("invalid-raw-digest", CONNECTOR_DICTIONARY, "f" * 63),
        )
        for name, dictionary, raw_digest in cases:
            with self.subTest(name=name):
                source_factory = mock.Mock(side_effect=AssertionError("source socket opened"))
                target_factory = mock.Mock(side_effect=AssertionError("target socket opened"))
                with (
                    mock.patch.object(
                        self.coordinator,
                        "_source_connector_factory",
                        source_factory,
                    ),
                    mock.patch.object(
                        self.coordinator,
                        "_target_store_factory",
                        target_factory,
                    ),
                    self.assertRaises(LoaderPolicyInvalid),
                ):
                    self.coordinator._run_initial_with_inputs(
                        loader_config(),
                        source_config=source_config,
                        source_contract=contract,
                        columns=source_config.column_map,
                        policy=approved_policy(),
                        dictionary=dictionary,
                        species_dictionary_artifact_sha256=raw_digest,
                    )
                source_factory.assert_not_called()
                target_factory.assert_not_called()

    def test_run_load_semantic_dictionary_mismatch_stops_before_source_config_and_sockets(
        self,
    ) -> None:
        changed_artifact = (
            b"SPECIES_NO,SCIENTIFIC,COMMON_NAM,SENSITIVE\nOTHER-1,Different species,Different,No\n"
        )
        config = approved_artifact_config()
        config = dataclasses.replace(
            config,
            species_dictionary=SpeciesDictionaryConfig(
                csv_path=Path("/controlled/changed-species-dictionary.csv"),
                expected_raw_sha256=hashlib.sha256(changed_artifact).hexdigest(),
                _artifact=changed_artifact,
            ),
        )
        source_config_loader = mock.Mock(side_effect=AssertionError("source config was read"))
        source_factory = mock.Mock(side_effect=AssertionError("source socket opened"))
        target_factory = mock.Mock(side_effect=AssertionError("target socket opened"))
        with (
            mock.patch.object(
                self.coordinator,
                "load_source_config",
                source_config_loader,
            ),
            mock.patch.object(self.coordinator, "_source_connector_factory", source_factory),
            mock.patch.object(self.coordinator, "_target_store_factory", target_factory),
            self.assertRaises(LoaderPolicyInvalid),
        ):
            self.coordinator.run_load(config, LoadMode.INITIAL)
        source_config_loader.assert_not_called()
        source_factory.assert_not_called()
        target_factory.assert_not_called()

    def test_run_load_parses_the_snapshotted_dictionary_bytes_before_release_gate(self) -> None:
        parser = mock.Mock(
            wraps=self.coordinator.parse_species_dictionary_artifact,
        )
        with (
            mock.patch.object(
                self.coordinator,
                "parse_species_dictionary_artifact",
                parser,
            ),
            self.assertRaises(LoaderReleaseBlocked),
        ):
            self.coordinator.run_load(approved_artifact_config(), LoadMode.INITIAL)
        parser.assert_called_once_with(SPECIES_DICTIONARY_ARTIFACT)

    def test_lock_contention_stops_before_the_source_snapshot_opens(self) -> None:
        target = FakeTargetStore(
            self.coordinator,
            active_release=OLD_RELEASE_ID,
            lock_failure=LoaderAlreadyRunning(),
        )
        with self.assertRaises(LoaderAlreadyRunning):
            self.run_initial([(disposition(1),)], target=target)
        self.assertEqual(target.active_release, OLD_RELEASE_ID)
        self.assertEqual(target.calls, ["acquire", "close"])
        self.assertTrue(target.closed)
        self.assertEqual(self.last_source.open_calls, [])
        self.assertFalse(self.last_snapshot.entered)

    def test_initial_load_refuses_an_existing_active_release_before_source(self) -> None:
        target = FakeTargetStore(self.coordinator, active_release=OLD_RELEASE_ID)
        with self.assertRaises(LoaderCandidateInvalid):
            self.run_initial([(disposition(1),)], target=target)
        self.assertEqual(target.active_release, OLD_RELEASE_ID)
        self.assertEqual(self.last_source.open_calls, [])
        self.assertFalse(self.last_snapshot.entered)
        self.assertEqual(target.failed_codes, ["LOADER_CANDIDATE_INVALID"])


class TestCompatibilityIdentity(CoordinatorCase):
    def test_target_preflight_binds_versions_environment_and_login_posture(self) -> None:
        session_sql = self.coordinator.TARGET_SESSION_SQL
        for required_fragment in (
            "current_setting('server_version_num')",
            "pg_catalog.pg_extension",
            "deployment_login.rolsuper",
            "deployment_login.rolbypassrls",
            "pg_catalog.pg_auth_members",
        ):
            self.assertIn(required_fragment, session_sql)
        self.assertEqual(
            self.coordinator.TARGET_IDENTITY_HEADER,
            ("environment_id", "database_name"),
        )
        self.assertIn(
            "loader_control.deployment_identity",
            self.coordinator.TARGET_IDENTITY_SQL,
        )

    def test_compatibility_binds_stable_inputs_not_snapshot_counts_or_time(self) -> None:
        arguments = {
            "source_contract_version": "source-v1",
            "source_contract_sha256": "1" * 64,
            "observed_view_definition_sha256": "2" * 64,
            "observed_view_identity_sha256": "3" * 64,
            "projection_sha256": "4" * 64,
            "publication_policy_version": "policy-v1",
            "publication_policy_sha256": "5" * 64,
            "policy_approval_sha256": "6" * 64,
            "species_dictionary_sha256": "7" * 64,
            "sensitivity_snapshot_sha256": "8" * 64,
            "reconciliation_key_sha256": "9" * 64,
        }
        first = self.coordinator._compatibility_sha256(**arguments)
        self.assertRegex(first, r"^[0-9a-f]{64}$")

        parameters = inspect.signature(self.coordinator._compatibility_sha256).parameters
        self.assertNotIn("captured_at_utc", parameters)
        self.assertNotIn("rows_seen", parameters)
        self.assertNotIn("sensitivity_buckets", parameters)

        for name, value in arguments.items():
            with self.subTest(bound_input=name):
                changed = dict(arguments)
                changed[name] = f"{value}-changed"
                self.assertNotEqual(
                    self.coordinator._compatibility_sha256(**changed),
                    first,
                )

    def test_terminal_failure_cleanup_gets_bounded_grace_after_workload_deadline(self) -> None:
        store = object.__new__(self.coordinator._PostgreSQLTargetStore)
        store._config = loader_config()
        store._absolute_deadline = 90.0
        handle = self.coordinator._CandidateHandle(
            job_id=self.coordinator.uuid4(),
            release_id=self.coordinator.uuid4(),
            base_release_id=None,
        )
        observed_deadlines: list[float] = []
        store._call_fail_candidate = lambda _handle, _code: observed_deadlines.append(
            store._absolute_deadline
        )
        store._read_failure_state = lambda _handle: self.coordinator._FailureState(
            release_status="failed",
            job_status="failed",
            failure_code="LOADER_EXECUTION_FAILED",
            cleanup_pending=True,
            active_release_id=None,
            failure_event_count=1,
        )

        def cleanup_times_out(_handle):
            observed_deadlines.append(store._absolute_deadline)
            raise RuntimeError("private cleanup timeout")

        store._discard_failed_candidate = cleanup_times_out

        with mock.patch.object(self.coordinator.time, "monotonic", return_value=100.0):
            store.fail(handle, "LOADER_EXECUTION_FAILED")

        self.assertEqual(observed_deadlines, [105.0, 105.0])
        self.assertEqual(store._absolute_deadline, 90.0)

    def test_terminal_cleanup_does_not_inherit_a_long_remaining_workload_deadline(self) -> None:
        store = object.__new__(self.coordinator._PostgreSQLTargetStore)
        store._config = loader_config()
        store._absolute_deadline = 7_300.0
        handle = self.coordinator._CandidateHandle(
            job_id=self.coordinator.uuid4(),
            release_id=self.coordinator.uuid4(),
            base_release_id=None,
        )
        observed_deadlines: list[float] = []
        store._call_fail_candidate = lambda _handle, _code: observed_deadlines.append(
            store._absolute_deadline
        )
        store._read_failure_state = lambda _handle: self.coordinator._FailureState(
            release_status="failed",
            job_status="failed",
            failure_code="LOADER_EXECUTION_FAILED",
            cleanup_pending=True,
            active_release_id=None,
            failure_event_count=1,
        )
        store._discard_failed_candidate = lambda _handle: observed_deadlines.append(
            store._absolute_deadline
        )

        with mock.patch.object(self.coordinator.time, "monotonic", return_value=100.0):
            store.fail(handle, "LOADER_EXECUTION_FAILED")

        self.assertEqual(observed_deadlines, [105.0, 105.0])
        self.assertEqual(store._absolute_deadline, 7_300.0)

    def test_reused_release_cleanup_is_bounded_and_cannot_reverse_success(self) -> None:
        store = object.__new__(self.coordinator._PostgreSQLTargetStore)
        store._config = loader_config()
        store._absolute_deadline = 7_300.0
        handle = self.coordinator._CandidateHandle(
            job_id=self.coordinator.uuid4(),
            release_id=self.coordinator.uuid4(),
            base_release_id=None,
        )
        summary = self.coordinator._CandidateSummary(
            source_rows=5,
            published_records=0,
            distribution_cells=1,
            candidate_sha256="a" * 64,
        )
        result = self.coordinator._ActivationResult(
            run_id=handle.job_id,
            release_id=self.coordinator.uuid4(),
            source_rows=5,
            published_records=0,
            distribution_cells=1,
            candidate_sha256="a" * 64,
        )
        store._activate_candidate = lambda _handle, _summary: result
        observed_deadlines: list[float] = []

        def cleanup_times_out(_release_id):
            observed_deadlines.append(store._absolute_deadline)
            raise RuntimeError("synthetic cleanup timeout")

        store._discard_inactive_release = cleanup_times_out
        with mock.patch.object(self.coordinator.time, "monotonic", return_value=100.0):
            activated = store.activate(handle, summary)

        self.assertEqual(activated, result)
        self.assertEqual(observed_deadlines, [105.0])
        self.assertEqual(store._absolute_deadline, 7_300.0)

    def test_begin_ack_reconciliation_restores_the_workload_deadline(self) -> None:
        store = object.__new__(self.coordinator._PostgreSQLTargetStore)
        store._config = loader_config()
        store._absolute_deadline = 120.0
        attempt = self.coordinator._CandidateHandle(
            job_id=self.coordinator.uuid4(),
            release_id=self.coordinator.uuid4(),
            base_release_id=None,
        )
        store._read_known_begin = lambda _attempt: attempt

        with mock.patch.object(self.coordinator.time, "monotonic", return_value=100.0):
            recovered = store._recover_begin_ack(
                SOURCE_ID,
                attempt,
                allow_retry=True,
            )

        self.assertEqual(recovered, attempt)
        self.assertEqual(store._absolute_deadline, 120.0)


class TestBoundedSafeStaging(CoordinatorCase):
    def test_public_entry_withholds_unlisted_ambiguous_and_id_name_mismatch_rows(
        self,
    ) -> None:
        dictionary_artifact = (
            SPECIES_DICTIONARY_ARTIFACT
            + b"AMB-1,Ambiguous species,Ambiguous one,No\n"
            + b"AMB-2,Ambiguous species,Ambiguous two,Yes\n"
        )
        dictionary = self.coordinator.parse_species_dictionary_artifact(dictionary_artifact)
        policy = dataclasses.replace(
            approved_policy(),
            species_dictionary_sha256=dictionary.digest(),
            approval_digest=None,
        )
        policy = dataclasses.replace(
            policy,
            approval_digest=policy._expected_approval_digest(),
        )
        policy.validate()
        policy.assert_approved()
        policy_artifact = json.dumps(
            policy.approval_artifact(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        config = dataclasses.replace(
            loader_config(maximum=3),
            publication=PublicationConfig(
                policy_path=Path("/controlled/public-entry-policy.json"),
                expected_sha256=hashlib.sha256(policy_artifact).hexdigest(),
                public_id_secret_env="BRERC_PUBLIC_ID_TEST_SECRET",  # noqa: S106
                _artifact=policy_artifact,
                _public_id_secret=policy.public_id_salt.encode("utf-8"),
            ),
            species_dictionary=SpeciesDictionaryConfig(
                csv_path=Path("/controlled/public-entry-species-dictionary.csv"),
                expected_raw_sha256=hashlib.sha256(dictionary_artifact).hexdigest(),
                _artifact=dictionary_artifact,
            ),
        )
        contract = approved_contract()
        source_config = connector_config(contract)
        connection = FakeConnection(
            row_batches=[
                [
                    source_row("1.00")
                    | {
                        "species_no": "UNLISTED-1",
                        "scientific_name": "Unlisted species",
                    },
                    source_row("2.00")
                    | {
                        "species_no": "5088",
                        "scientific_name": "Synthetic species alpha",
                    },
                    source_row("3.00")
                    | {
                        "species_no": "AMB-1",
                        "scientific_name": "Ambiguous species",
                    },
                ],
                [],
            ]
        )
        target = FakeTargetStore(self.coordinator)
        with (
            mock.patch.object(self.coordinator, "BRERC_MAIN_DATA_DASH", contract),
            mock.patch.object(
                self.coordinator,
                "load_source_config",
                return_value=source_config,
            ),
            mock.patch.object(
                self.coordinator,
                "_target_store_factory",
                return_value=target,
            ),
            mock.patch(
                "brerc_source.postgres._default_connection_factory",
                return_value=connection,
            ),
            self.assertRaises(LoaderCandidateInvalid),
        ):
            self.coordinator.run_load(config, LoadMode.INITIAL)

        self.assertEqual(
            [item.withheld_reason for item in target.staged],
            [
                "species-not-permitted",
                "species-identity-mismatch",
                "ambiguous-species-name",
            ],
        )
        self.assertTrue(all(item.record is None for item in target.staged))
        self.assertFalse(target.activated)

    def test_safe_batches_are_staged_without_raw_values_and_then_activated(self) -> None:
        batches = [
            tuple(disposition(number) for number in range(1, 4)),
            tuple(disposition(number) for number in range(4, 6)),
        ]
        report, source, snapshot, target = self.run_initial(batches)

        self.assertEqual(target.stage_sizes, [3, 2])
        self.assertLessEqual(max(target.stage_sizes), loader_config().runtime.batch_size)
        self.assertEqual(target.finalize_seen_count, 5)
        self.assertEqual(
            target.calls,
            [
                "acquire",
                "begin_initial",
                "stage_batch",
                "stage_batch",
                "finalize",
                "activate",
                "close",
            ],
        )
        self.assertTrue(source.open_calls)
        self.assertIs(source.open_calls[0]["dictionary"], CONNECTOR_DICTIONARY)
        self.assertTrue(snapshot.entered)
        self.assertTrue(snapshot.exhausted)
        self.assertTrue(snapshot.closed)
        self.assertTrue(target.closed)
        self.assertTrue(target.activated)
        self.assertEqual(str(target.active_release), report.release_id)
        self.assertTrue(report.activated)
        self.assertEqual(
            target.finalize_kwargs["species_dictionary_artifact_sha256"],
            SPECIES_DICTIONARY_ARTIFACT_SHA256,
        )
        self.assertEqual(
            target.finalize_kwargs["species_dictionary_sha256"],
            CONNECTOR_DICTIONARY.digest(),
        )

        target.assert_private(target.staged)
        rendered = repr(target.staged)
        for sentinel in RAW_SENTINELS:
            self.assertNotIn(sentinel, rendered)

    def test_source_batches_larger_than_the_target_bound_are_split_not_rejected(self) -> None:
        # Source and target deployments have independent batch controls. A
        # reviewed source config may yield 101 rows while the loader is bounded
        # to target writes of 100; the coordinator must rechunk safe rows.
        batch = tuple(disposition(number) for number in range(101))
        target = FakeTargetStore(self.coordinator, maximum_batch_size=100)
        report, _source, _snapshot, target = self.run_initial(
            [batch],
            config=loader_config(maximum=200),
            target=target,
            source_batch_size=500,
        )
        self.assertEqual(report.source_rows, 101)
        self.assertEqual(target.stage_sizes, [100, 1])

    def test_global_suppression_is_independent_of_source_batch_boundaries(self) -> None:
        policy = minimum_count_policy(3)
        # The three-member cohort is deliberately split 2 + 1. Processing
        # suppression per batch would suppress all three; whole-run finalisation
        # must publish the cohort and suppress the separate singleton.
        batches = [
            (disposition(1), disposition(2)),
            (disposition(3), disposition(4, species_id="other")),
        ]
        _report, _source, _snapshot, target = self.run_initial(
            batches,
            policy=policy,
        )
        self.assertEqual(target.finalize_seen_count, 4)
        self.assertEqual(
            [item.record.record_id for item in target.published_after_suppression],
            [disposition(number).record.record_id for number in range(1, 4)],
        )


class TestFailureAtomicity(CoordinatorCase):
    def test_observed_dictionary_digest_mismatch_refuses_finalization_and_activation(
        self,
    ) -> None:
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderCandidateInvalid):
            self.run_initial(
                [(disposition(1),)],
                target=target,
                observed_dictionary_sha256="f" * 64,
            )
        self.assertNotIn("finalize", target.calls)
        self.assertNotIn("activate", target.calls)
        self.assertEqual(target.failed_codes, ["LOADER_CANDIDATE_INVALID"])
        self.assertTrue(target.closed)

    def test_confirmed_failure_survives_later_close_error(self) -> None:
        target = FakeTargetStore(
            self.coordinator,
            stage_failure_at=1,
            close_failure=RuntimeError("private destination close detail"),
        )
        with self.assertRaises(LoaderExecutionFailed) as raised:
            self.run_initial([(disposition(1),)], target=target)
        self.assertEqual(raised.exception.code, "LOADER_EXECUTION_FAILED")
        self.assertEqual(target.failed_codes, ["LOADER_EXECUTION_FAILED"])
        self.assertTrue(target.closed)

    def test_close_error_after_committed_activation_cannot_report_false_failure(self) -> None:
        target = FakeTargetStore(
            self.coordinator,
            close_failure=RuntimeError("private destination socket detail"),
        )
        report, _source, _snapshot, target = self.run_initial(
            [(disposition(1),)],
            target=target,
        )
        self.assertTrue(report.activated)
        self.assertTrue(target.activated)
        self.assertTrue(target.closed)
        self.assertEqual(str(target.active_release), report.release_id)
        self.assertEqual(target.failed_codes, [])

    def test_begin_commit_ack_loss_uses_the_known_handle_to_remove_the_open_job(self) -> None:
        target = FakeTargetStore(
            self.coordinator,
            begin_failure_after_commit=True,
        )
        with self.assertRaises(LoaderExecutionFailed) as raised:
            self.run_initial([(disposition(1),)], target=target)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertEqual(target.failed_codes, ["LOADER_EXECUTION_FAILED"])
        self.assertFalse(target.open_candidate)
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertTrue(target.closed)
        self.assertEqual(self.last_source.open_calls, [])
        self.assertFalse(self.last_snapshot.entered)

    def test_duplicate_source_token_across_batches_never_changes_active_release(self) -> None:
        duplicate = disposition(1)
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderCandidateInvalid):
            self.run_initial([(duplicate,), (duplicate,)], target=target)
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertTrue(target.closed)
        self.assertTrue(self.last_snapshot.closed)
        self.assertEqual(target.calls.count("activate"), 0)
        self.assertEqual(target.failed_codes, ["LOADER_CANDIDATE_INVALID"])

    def test_nonempty_source_with_every_row_withheld_cannot_replace_the_dashboard(self) -> None:
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderCandidateInvalid):
            self.run_initial(
                [(withheld_disposition(1), withheld_disposition(2))],
                target=target,
            )
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertEqual(target.failed_codes, ["LOADER_CANDIDATE_INVALID"])

    def test_global_suppression_cannot_activate_an_empty_public_candidate(self) -> None:
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderCandidateInvalid):
            self.run_initial(
                [(disposition(1),), (disposition(2),)],
                policy=minimum_count_policy(3),
                target=target,
            )
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertEqual(target.failed_codes, ["LOADER_CANDIDATE_INVALID"])

    def test_source_count_bounds_are_inclusive_and_outside_values_are_rejected(self) -> None:
        for rows in (2, 3):
            with self.subTest(rows=rows, outcome="accepted"):
                report, *_ = self.run_initial(
                    [tuple(disposition(number) for number in range(rows))],
                    config=loader_config(minimum=2, maximum=3),
                )
                self.assertEqual(report.source_rows, rows)

        for rows in (1, 4):
            with self.subTest(rows=rows, outcome="rejected"):
                target = FakeTargetStore(self.coordinator)
                with self.assertRaises(LoaderSourceCountRejected):
                    self.run_initial(
                        [tuple(disposition(number) for number in range(rows))],
                        config=loader_config(minimum=2, maximum=3),
                        target=target,
                    )
                self.assertIsNone(target.active_release)
                self.assertFalse(target.activated)
                self.assertEqual(target.failed_codes, ["LOADER_SOURCE_COUNT_REJECTED"])
                self.assertTrue(self.last_snapshot.closed)

    def test_source_growth_stops_before_a_chunk_would_exceed_the_approved_maximum(self) -> None:
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderSourceCountRejected):
            self.run_initial(
                [(disposition(1), disposition(2)), (disposition(3),)],
                config=loader_config(minimum=1, maximum=2),
                target=target,
            )
        self.assertEqual(target.stage_sizes, [2])
        self.assertEqual(len(target.staged), 2)
        self.assertFalse(target.activated)
        self.assertTrue(self.last_snapshot.closed)
        self.assertEqual(target.failed_codes, ["LOADER_SOURCE_COUNT_REJECTED"])

    def test_stage_failure_closes_both_sides_and_exposes_only_fixed_context(self) -> None:
        target = FakeTargetStore(self.coordinator, stage_failure_at=2)
        with self.assertRaises(LoaderExecutionFailed) as raised:
            self.run_initial(
                [(disposition(1),), (disposition(2),)],
                target=target,
            )
        self.assertEqual(
            str(raised.exception),
            "LOADER_EXECUTION_FAILED: the release loader operation failed",
        )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertTrue(target.closed)
        self.assertTrue(self.last_snapshot.closed)
        self.assertEqual(target.failed_codes, ["LOADER_EXECUTION_FAILED"])
        for sentinel in RAW_SENTINELS:
            self.assertNotIn(sentinel, str(raised.exception))

    def test_source_exception_is_redacted_and_snapshot_is_always_closed(self) -> None:
        target = FakeTargetStore(self.coordinator)
        with self.assertRaises(LoaderExecutionFailed) as raised:
            self.run_initial(
                [(disposition(1),), (disposition(2),)],
                target=target,
                fail_after_batches=1,
            )
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertTrue(target.closed)
        self.assertTrue(self.last_snapshot.closed)
        self.assertEqual(target.failed_codes, ["LOADER_EXECUTION_FAILED"])
        self.assertNotIn("RAW-UNIQUE-001", str(raised.exception))

    def test_one_whole_run_deadline_cancels_and_keeps_candidate_invisible(self) -> None:
        # First value creates the deadline; the following values allow setup
        # and one staged batch. The next batch crosses the single run deadline.
        clock = iter((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 301.0))
        target = FakeTargetStore(self.coordinator)
        with (
            mock.patch.object(
                self.coordinator.time,
                "monotonic",
                side_effect=lambda: next(clock),
            ),
            self.assertRaises(LoaderExecutionFailed),
        ):
            self.run_initial(
                [(disposition(1),), (disposition(2),)],
                target=target,
            )
        self.assertEqual(target.cancelled, 1)
        self.assertIsNone(target.active_release)
        self.assertFalse(target.activated)
        self.assertTrue(target.closed)
        self.assertTrue(self.last_snapshot.closed)
        self.assertEqual(target.failed_codes, ["LOADER_EXECUTION_FAILED"])

    def test_deadline_crossing_after_activation_cannot_turn_success_into_failure(self) -> None:
        # Once activation has committed and returned, the release is public.
        # A post-activation clock check must not report failure or attempt to
        # fail the now-active release.
        clock = iter((*([0.0] * 9), 301.0))
        target = FakeTargetStore(self.coordinator)
        with mock.patch.object(
            self.coordinator.time,
            "monotonic",
            side_effect=lambda: next(clock),
        ):
            report, *_ = self.run_initial([(disposition(1),)], target=target)
        self.assertTrue(report.activated)
        self.assertTrue(target.activated)
        self.assertEqual(str(target.active_release), report.release_id)
        self.assertEqual(target.failed_codes, [])


if __name__ == "__main__":
    unittest.main()
