"""Regression tests for the local workflow-dependency smoke guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.guard_workflow_dependencies import check


class TestWorkflowDependencyGuard(unittest.TestCase):
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
