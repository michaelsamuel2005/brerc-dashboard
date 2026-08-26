"""Regression tests for the local workflow-dependency smoke guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.guard_workflow_dependencies import WORKFLOW_DEPENDENCIES, check


class TestWorkflowDependencyGuard(unittest.TestCase):
    def test_ci_manifest_covers_the_publication_api_lifecycle(self) -> None:
        dependencies = set(WORKFLOW_DEPENDENCIES[".github/workflows/ci.yml"])
        self.assertTrue(
            {
                "api/app",
                "api/app_tests",
                "api/package_tests",
                "api/loader_tests/test_postgis16_destination_integration.py",
                "api/loader_tests/setup_postgis16_destination.sh",
                "api/loader_tests/setup_postgres16_e2e_source.sh",
                "db/migrations/0001_publication_store.sql",
                "db/roles.sql",
            }.issubset(dependencies)
        )
        self.assertTrue(
            {
                "api/tests/test_b0_integration.py",
                "api/tests/test_b8_query_params.py",
                "api/tests/test_b8_species_info.py",
                "api/tests/test_smoke.py",
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
