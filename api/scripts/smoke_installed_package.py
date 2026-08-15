#!/usr/bin/env python3
"""Smoke-test the installed ``brerc-api`` wheel, away from its source tree.

Run this with the Python interpreter from a clean virtual environment after
installing the wheel.  CI changes to a temporary directory first and passes the
checkout's ``api`` directory via ``--source-root``; this catches a wheel that
builds successfully but omits the import package.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import pkgutil
import sys
from pathlib import Path


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        required=True,
        help="checkout's api directory; the imported package must not resolve here",
    )
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    package = importlib.import_module("etl")
    package_file = Path(package.__file__ or "").resolve()

    if _is_within(package_file, source_root):
        print(
            f"FAIL: imported etl from the source tree ({package_file}), not the wheel.",
            file=sys.stderr,
        )
        return 1

    module_names = sorted(
        module.name for module in pkgutil.iter_modules(package.__path__, prefix="etl.")
    )
    if not module_names:
        print("FAIL: the installed etl package contains no modules.", file=sys.stderr)
        return 1
    packaged_tests = [name for name in module_names if name.rsplit(".", 1)[-1].startswith("test_")]
    if packaged_tests:
        print(
            f"FAIL: production wheel contains test module(s): {packaged_tests}",
            file=sys.stderr,
        )
        return 1
    if importlib.util.find_spec("etl.test_source_contract") is not None:
        print(
            "FAIL: synthetic source-approval tests are importable from the wheel.", file=sys.stderr
        )
        return 1

    for module_name in module_names:
        importlib.import_module(module_name)

    # The connector package must be present in the base wheel and importable
    # without PyYAML or Psycopg. Both dependencies are intentionally lazy and
    # installed only through a connector extra.
    connector_package = importlib.import_module("brerc_source")
    connector_file = Path(connector_package.__file__ or "").resolve()
    if _is_within(connector_file, source_root):
        print(
            f"FAIL: imported brerc_source from the source tree ({connector_file}), not the wheel.",
            file=sys.stderr,
        )
        return 1
    connector_modules = sorted(
        module.name
        for module in pkgutil.iter_modules(
            connector_package.__path__,
            prefix="brerc_source.",
        )
    )
    if not connector_modules:
        print("FAIL: the installed brerc_source package contains no modules.", file=sys.stderr)
        return 1
    for module_name in connector_modules:
        importlib.import_module(module_name)

    loader_package = importlib.import_module("brerc_loader")
    loader_file = Path(loader_package.__file__ or "").resolve()
    if _is_within(loader_file, source_root):
        print(
            f"FAIL: imported brerc_loader from the source tree ({loader_file}), not the wheel.",
            file=sys.stderr,
        )
        return 1
    loader_modules = sorted(
        module.name
        for module in pkgutil.iter_modules(loader_package.__path__, prefix="brerc_loader.")
    )
    if not loader_modules:
        print("FAIL: the installed brerc_loader package contains no modules.", file=sys.stderr)
        return 1
    for module_name in loader_modules:
        importlib.import_module(module_name)

    distribution = importlib.metadata.distribution("brerc-api")
    distribution_files = distribution.files or ()
    licence_files = [
        path for path in distribution_files if ".dist-info/licenses/" in path.as_posix()
    ]
    if not licence_files:
        print("FAIL: the wheel does not contain its licence notice.", file=sys.stderr)
        return 1

    print(f"OK: brerc-api {distribution.version} imports from {package_file.parent}.")
    print(f"    imported {len(module_names)} packaged ETL module(s).")
    print(f"    imported {len(connector_modules)} packaged connector module(s), dependency-free.")
    print(f"    imported {len(loader_modules)} packaged loader module(s), dependency-free.")
    print(f"    licence notice: {licence_files[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
