"""Regression tests for the standard-library import boundary guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.guard_stdlib_only import check


class TestPackageImports(unittest.TestCase):
    def test_package_root_is_a_local_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = Path(temp_dir, "etl")
            etl_dir.mkdir()
            Path(etl_dir, "__init__.py").write_text("", encoding="utf-8")
            Path(etl_dir, "consumer.py").write_text(
                "from etl.contract import PublicRecord\n",
                encoding="utf-8",
            )

            self.assertEqual(check(etl_dir), [])

    def test_true_third_party_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = Path(temp_dir, "etl")
            etl_dir.mkdir()
            Path(etl_dir, "boundary.py").write_text(
                "import definitely_not_a_stdlib_module\n",
                encoding="utf-8",
            )

            self.assertEqual(
                check(etl_dir),
                [
                    "boundary.py: imports 'definitely_not_a_stdlib_module', which is not "
                    "in the standard library and not a module of api/etl."
                ],
            )


if __name__ == "__main__":
    unittest.main()
