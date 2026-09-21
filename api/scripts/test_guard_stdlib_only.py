"""Regression tests for the standard-library import boundary guard."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.guard_stdlib_only import check


def _write_package(temp_dir: str, files: dict[str, str]) -> Path:
    """Create ``<temp_dir>/etl`` holding ``files`` (relative path -> source)."""
    etl_dir = Path(temp_dir, "etl")
    etl_dir.mkdir()
    for name, source in files.items():
        target = etl_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return etl_dir


class TestPackageImports(unittest.TestCase):
    def test_package_root_is_a_local_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "__init__.py": "",
                    "contract.py": "class PublicRecord: ...\n",
                    "consumer.py": "from etl.contract import PublicRecord\n",
                },
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


class TestBoundarySet(unittest.TestCase):
    """A local import passes only when it names a module that is itself checked."""

    def test_absolute_import_of_sibling_outside_the_checked_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "__init__.py": "",
                    "db.py": "import psycopg\n",
                    "boundary.py": (
                        "import etl.db\nfrom etl.db import connect\nfrom etl import db\n"
                    ),
                },
            )

            self.assertEqual(
                check(etl_dir, frozenset({"__init__.py", "boundary.py"})),
                [
                    "boundary.py: imports 'etl.db', a module of api/etl that is not in "
                    "the checked boundary set."
                ],
            )

    def test_relative_import_of_sibling_outside_the_checked_set_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "__init__.py": "",
                    "db.py": "import psycopg\n",
                    "boundary.py": "from .db import connect\nfrom . import db\n",
                },
            )

            self.assertEqual(
                check(etl_dir, frozenset({"__init__.py", "boundary.py"})),
                [
                    "boundary.py: imports 'etl.db', a module of api/etl that is not in "
                    "the checked boundary set."
                ],
            )

    def test_subpackage_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "__init__.py": "",
                    "safety_gate/__init__.py": "",
                    "safety_gate/rules.py": "",
                    "boundary.py": (
                        "from .safety_gate.rules import classify\n"
                        "from etl.safety_gate import rules\n"
                        "from . import safety_gate\n"
                    ),
                },
            )

            self.assertEqual(
                check(etl_dir, frozenset({"__init__.py", "boundary.py"})),
                [
                    "boundary.py: imports 'etl.safety_gate', a module of api/etl that "
                    "is not in the checked boundary set.",
                    "boundary.py: imports 'etl.safety_gate.rules', a module of api/etl "
                    "that is not in the checked boundary set.",
                ],
            )

    def test_parent_package_import_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {"boundary.py": "from ..shared import helper\nfrom .. import other\n"},
            )

            self.assertEqual(
                check(etl_dir),
                [
                    "boundary.py: imports '..', which climbs out of api/etl into a parent package.",
                    "boundary.py: imports '..shared', which climbs out of api/etl into "
                    "a parent package.",
                ],
            )

    def test_from_package_import_sibling_is_accepted_when_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "contract.py": "",
                    "boundary.py": "from etl import contract\n",
                },
            )

            self.assertEqual(check(etl_dir, frozenset({"boundary.py", "contract.py"})), [])

    def test_from_package_import_exported_name_resolves_to_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "__init__.py": "SOME_NAME = 1\n",
                    "boundary.py": "from etl import SOME_NAME\n",
                },
            )

            self.assertEqual(check(etl_dir, frozenset({"__init__.py", "boundary.py"})), [])
            self.assertEqual(
                check(etl_dir, frozenset({"boundary.py"})),
                [
                    "boundary.py: imports 'etl.__init__', a module of api/etl that is "
                    "not in the checked boundary set."
                ],
            )

    def test_sibling_in_the_checked_set_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            etl_dir = _write_package(
                temp_dir,
                {
                    "contract.py": "",
                    "boundary.py": (
                        "from .contract import PublicRecord\n"
                        "from . import contract\n"
                        "import etl.contract\n"
                        "from etl.contract import PublicCell\n"
                    ),
                },
            )

            self.assertEqual(check(etl_dir, frozenset({"boundary.py", "contract.py"})), [])


if __name__ == "__main__":
    unittest.main()
