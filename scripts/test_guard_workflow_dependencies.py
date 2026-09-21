"""Regression tests for the local workflow-dependency smoke guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.guard_workflow_dependencies import WORKFLOW_DEPENDENCIES, check


class TestWorkflowDependencyGuard(unittest.TestCase):
    def test_systemd_validation_is_pinned_to_the_reviewed_ubuntu_baseline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        connector_package = workflow.split("  connector-package:", 1)[1].split(
            "\n  loader-unit:", 1
        )[0]
        self.assertIn("runs-on: ubuntu-24.04", connector_package)
        self.assertIn("verify_systemd_templates.py", connector_package)

    def test_retained_legacy_e2e_is_explicitly_opted_in_by_ci(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        harness = (root / "db" / "test" / "run_e2e.py").read_text(encoding="utf-8")
        opt_in = 'BRERC_ENABLE_LEGACY_E2E_FOR_TESTS: "1"'
        self.assertIn(opt_in, workflow)
        self.assertIn('os.environ.get("BRERC_ENABLE_LEGACY_E2E_FOR_TESTS")', harness)
        self.assertIn(
            "Run the retained legacy synthetic source-to-publication E2E test", workflow
        )

    def test_ci_manifest_covers_the_publication_api_lifecycle(self) -> None:
        dependencies = set(WORKFLOW_DEPENDENCIES[".github/workflows/ci.yml"])
        self.assertTrue(
            {
                "api/app",
                "api/app_tests",
                "api/brerc_loader",
                "api/brerc_source",
                "api/deployment_tests",
                "api/package_tests",
                "api/etl/streaming.py",
                "api/loader_tests",
                "api/loader_tests/test_postgis16_destination_integration.py",
                "api/loader_tests/test_initial_approval_consumer.py",
                "api/loader_tests/test_initial_loader_deployment.py",
                "api/loader_tests/test_refresh_scheduler_deployment.py",
                "api/loader_tests/test_release_evidence_verifier.py",
                "api/loader_tests/setup_postgis16_destination.sh",
                "api/loader_tests/setup_postgres16_e2e_source.sh",
                "Caddyfile",
                "db/test/_run_pipeline.py",
                "db/test/e2e_sensitive_species.csv",
                "db/test/e2e_source_data.sql",
                "db/test/e2e_source_mock.sql",
                "db/test/run_e2e.py",
                "deploy/refresh/README.md",
                "deploy/refresh/brerc-loader-refresh-approval-guard.service.example",
                "deploy/refresh/brerc-loader-refresh.service.example",
                "deploy/refresh/brerc-loader-refresh.timer.example",
                "deploy/refresh/loader-runtime.env.example",
                "deploy/initial/README.md",
                "deploy/initial/brerc-loader-initial-quarantine.service.example",
                "deploy/initial/brerc-loader-initial.service.example",
                "deploy/initial/consume_initial_approval.py",
                "deploy/refresh/brerc-loader-refresh-quarantine.service.example",
                "deploy/validation/failed_attempt_evidence_query.sql",
                "deploy/validation/verify_failed_attempt_evidence.py",
                "deploy/validation/release_evidence_query.sql",
                "deploy/validation/verify_release_evidence.py",
                "deploy/validation/verify_systemd_templates.py",
                "db/migrations/0001_publication_store.sql",
                "db/migrations/0002_sensitive_record_action.sql",
                "db/migrations/0003_full_snapshot_refresh.sql",
                "db/migrations/0004_release_evidence.sql",
                "db/roles.sql",
                "deploy/production/brerc-public-api.service.example",
                "deploy/production/brerc-run-dashboard.service.example",
                "deploy/validation/audit_runtime_logins.sql",
                "deploy/validation/test_verify_systemd_examples.py",
                "deploy/validation/verify_systemd_examples.py",
                "docker-compose.yml",
                "docs/PUBLIC_SERVING_ARCHITECTURE.md",
                "docs/RUN_LOCALLY.md",
                "run-dashboard/app.py",
                "run-dashboard/requirements-dev.txt",
                "run-dashboard/requirements.txt",
                "run-dashboard/static",
                "run-dashboard/store.py",
                "run-dashboard/tests",
                "web/src/lib/api/endpoints.ts",
            }.issubset(dependencies)
        )
        self.assertTrue(
            {
                "api/tests/test_b0_integration.py",
                "api/tests/test_b8_query_params.py",
                "api/tests/test_b8_species_info.py",
                "api/tests/test_smoke.py",
                "api/tests/test_streaming.py",
            }.issubset(dependencies)
        )

    def test_ci_manifest_covers_every_browser_gate_entry_point(self) -> None:
        dependencies = set(WORKFLOW_DEPENDENCIES[".github/workflows/ci.yml"])
        self.assertTrue(
            {
                "web/e2e",
                "web/e2e/live_integration.spec.ts",
                "web/e2e/serialization.pw.test.ts",
                "web/package-lock.json",
                "web/package.json",
                "web/mutation/config.json",
                "web/mutation/mutate_inner.py",
                "web/mutation/run_disposable.py",
                "web/playwright.config.ts",
                "web/playwright.live.config.ts",
                "web/playwright.serialization.config.ts",
                "web/scripts/guard-bundle.mjs",
                "web/scripts/guard-forbidden.mjs",
                "web/scripts/screenshots.mjs",
                "web/tsconfig.a11y.json",
                "web/tsconfig.json",
                "web/vite.config.ts",
            }.issubset(dependencies)
        )

    def test_scale_manifest_covers_the_exact_migration_stack(self) -> None:
        dependencies = set(
            WORKFLOW_DEPENDENCIES[".github/workflows/loader-scale-acceptance.yml"]
        )
        self.assertTrue(
            {
                "db/migrations/0001_publication_store.sql",
                "db/migrations/0002_sensitive_record_action.sql",
                "db/migrations/0003_full_snapshot_refresh.sql",
                "db/migrations/0004_release_evidence.sql",
            }.issubset(dependencies)
        )

    def test_missing_dependency_and_unregistered_workflow_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflows = root / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "known.yml").write_text("name: known\n", encoding="utf-8")
            (workflows / "forgotten.yml").write_text(
                "name: forgotten\n", encoding="utf-8"
            )
            with patch(
                "scripts.guard_workflow_dependencies.WORKFLOW_DEPENDENCIES",
                {".github/workflows/known.yml": ("api/required.py",)},
            ):
                self.assertEqual(
                    check(root),
                    [
                        "unregistered workflow: .github/workflows/forgotten.yml",
                        ".github/workflows/known.yml: missing dependency: api/required.py",
                    ],
                )

    def test_complete_manifest_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workflow = root / ".github" / "workflows" / "known.yml"
            dependency = root / "api" / "required.py"
            workflow.parent.mkdir(parents=True)
            dependency.parent.mkdir(parents=True)
            workflow.write_text("name: known\n", encoding="utf-8")
            dependency.write_text("# present\n", encoding="utf-8")
            with patch(
                "scripts.guard_workflow_dependencies.WORKFLOW_DEPENDENCIES",
                {".github/workflows/known.yml": ("api/required.py",)},
            ):
                self.assertEqual(check(root), [])


if __name__ == "__main__":
    unittest.main()
