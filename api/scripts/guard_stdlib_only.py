#!/usr/bin/env python3
"""Fail if the ETL safety boundary imports anything outside the standard library.

WHY THIS IS A CI GATE AND NOT A COMMENT
---------------------------------------
`api/etl` decides which locations reach the public. Its correctness depends on
how it parses grid references, dates and species ids. A third-party package can
change any of those in a patch release - pandas has repeatedly changed date
inference, integer/NaN handling and string coercion between minor versions - and
the failure mode is not a crash. It is a record published at the wrong
resolution, or a sensitive taxon that stops matching, with a green test suite.

So the boundary is standard-library only, and this script makes that a fact
rather than an intention. Adding a dependency to the gate now requires deleting
a CI check, which is a conversation with a reviewer.

`cleaning.py` is exempt: it is exploratory, explicitly not part of the boundary,
and says so in its own docstring. Tests live outside the installable ``etl``
package and are not part of this runtime import scan.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: Modules that may import outside the standard library, with the reason.
#: Anything not listed here is part of the boundary.
EXEMPT: dict[str, str] = {
    "cleaning.py": "exploratory helper, explicitly not the safety boundary",
}


def _stdlib_names() -> frozenset[str]:
    """Top-level module names in this interpreter's standard library.

    `sys.stdlib_module_names` exists from Python 3.10, which is the project's
    floor. It is a frozenset of top-level names and includes builtins.
    """
    return frozenset(sys.stdlib_module_names)


def top_level_imports(source: str) -> set[str]:
    """Every top-level module name imported by a source file.

    Walks the whole AST, so an import inside a function or a `try` block is
    caught too - a lazily-imported dependency is still a dependency.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        # A relative import (level > 0) is local by definition, so only an
        # absolute `from X import ...` names an outside module.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def check(etl_dir: Path) -> list[str]:
    """Return one human-readable problem per offending import."""
    stdlib = _stdlib_names()
    # Tests intentionally use the installed-package form (``from etl ...``)
    # rather than relying on their current directory.  The package name is
    # therefore local just like the individual module names are.
    local = {etl_dir.name, *(p.stem for p in etl_dir.glob("*.py"))}
    problems: list[str] = []

    files = sorted(etl_dir.glob("*.py"))
    if not files:
        return [f"no Python files found under {etl_dir} - wrong path?"]

    for path in files:
        if path.name in EXEMPT:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            problems.append(f"{path.name}: could not read ({exc})")
            continue
        try:
            imports = top_level_imports(source)
        except SyntaxError as exc:
            problems.append(f"{path.name}: does not parse ({exc})")
            continue
        for name in sorted(imports):
            if name in stdlib or name in local or name == "__future__":
                continue
            problems.append(
                f"{path.name}: imports {name!r}, which is not in the standard "
                f"library and not a module of api/etl."
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--etl-dir",
        default="etl",
        help="directory holding the ETL modules (default: etl, relative to api/)",
    )
    args = parser.parse_args()

    etl_dir = Path(args.etl_dir).resolve()
    problems = check(etl_dir)

    if problems:
        print("FAIL: the ETL safety boundary must import only the standard library.")
        print()
        for problem in problems:
            print(f"  {problem}")
        print()
        print("If the dependency is genuinely necessary, that is a design decision:")
        print("record it in Decisions_Log.md and add the module to EXEMPT here,")
        print("with the reason. Do not delete this check.")
        return 1

    checked = sorted(p.name for p in etl_dir.glob("*.py") if p.name not in EXEMPT)
    print(f"OK: {len(checked)} ETL module(s) import only the standard library.")
    print(f"    exempt: {', '.join(sorted(EXEMPT)) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
