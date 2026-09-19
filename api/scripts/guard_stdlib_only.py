#!/usr/bin/env python3
"""Fail if the ETL safety boundary imports anything outside the standard library.

WHY THIS IS A CI GATE AND NOT A COMMENT
---------------------------------------
The publication modules in `api/etl` decide which locations reach the public.
Their correctness depends on how they parse grid references, dates and species ids. A third-party package can
change any of those in a patch release - pandas has repeatedly changed date
inference, integer/NaN handling and string coercion between minor versions - and
the failure mode is not a crash. It is a record published at the wrong
resolution, or a sensitive taxon that stops matching, with a green test suite.

So the boundary is standard-library only, and this script makes that a fact
rather than an intention. Adding a dependency to the gate now requires deleting
a CI check, which is a conversation with a reviewer.

The team's pandas-based nightly ETL coexists in the same package but is not a
publication-authority path. The explicit file set below prevents its dependencies
from weakening this narrower safety boundary. `cleaning.py` is exploratory and
is likewise outside the set. Tests live outside the installable ``etl`` package.

WHAT AN ALLOWED IMPORT LOOKS LIKE
---------------------------------
Every import in a checked module is resolved to the module it actually names,
and that module must be either in the standard library or one of the modules
being checked. A sibling may be named absolutely (``import etl.gridref``,
``from etl.gridref import x``, ``from etl import gridref``) or relatively
(``from .gridref import x``, ``from . import gridref``); both resolve to
``gridref.py`` and pass only when ``gridref.py`` is in the checked set.

Matching on the package name alone is not enough: ``etl.db`` imports psycopg
and ``etl.nightly_pipeline`` imports pandas, and a boundary module that reached
either through the package would inherit those dependencies unnoticed. So a
sibling outside the checked set fails, as does a subpackage
(``etl.safety_gate.rules`` is not a checked file) and a relative import that
climbs into a parent package (``from .. import x``). ``from etl import NAME``
where ``NAME`` is not a sibling file is a name that ``__init__.py`` exports, so
it is allowed exactly when ``__init__.py`` is in the checked set.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

#: Exact modules that form the publication-authority boundary. Adding or
#: removing a file is an explicit review decision; unrelated nightly ETL files
#: are never pulled into or exempted from this guarantee by accident.
PUBLICATION_BOUNDARY = frozenset(
    {
        "__init__.py",
        "aggregate.py",
        "contract.py",
        "filtering.py",
        "gridref.py",
        "identifiers.py",
        "pipeline.py",
        "policy.py",
        "sensitivity.py",
        "source_contract.py",
        "species.py",
        "view_identity.py",
    }
)

#: What an import resolves to; see :func:`resolve_imports`.
STDLIB = "stdlib"
THIRD_PARTY = "third_party"
LOCAL = "local"
PARENT = "parent"


def _stdlib_names() -> frozenset[str]:
    """Top-level module names in this interpreter's standard library.

    `sys.stdlib_module_names` exists from Python 3.10, which is the project's
    floor. It is a frozenset of top-level names and includes builtins.
    """
    return frozenset(sys.stdlib_module_names)


def _sibling(etl_dir: Path, name: str) -> str:
    """Resolve ``from <package> import <name>`` (or ``from . import <name>``).

    A sibling module file or subpackage directory of that name is the module
    imported; any other name (``*`` included) is something ``__init__.py``
    exports, so the import resolves to ``__init__``.
    """
    if (etl_dir / f"{name}.py").is_file() or (etl_dir / name).is_dir():
        return name
    return "__init__"


def resolve_imports(source: str, package: str, etl_dir: Path) -> set[tuple[str, str]]:
    """Every module a source file imports, as ``(kind, name)`` pairs.

    ``kind`` is :data:`STDLIB`, :data:`THIRD_PARTY` (``name`` is the top-level
    package), :data:`LOCAL` (``name`` is the sibling's dotted path relative to
    ``package``, e.g. ``"gridref"`` or ``"safety_gate.rules"``) or
    :data:`PARENT` (``name`` is a relative import that climbs out of ``package``).

    Walks the whole AST, so an import inside a function or a `try` block is
    caught too - a lazily-imported dependency is still a dependency.
    """
    stdlib = _stdlib_names()

    def absolute(dotted: str) -> tuple[str, str]:
        head, _, rest = dotted.partition(".")
        if head == package:
            return LOCAL, rest or "__init__"
        if head == "__future__" or head in stdlib:
            return STDLIB, head
        return THIRD_PARTY, head

    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(absolute(alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if level >= 2:
                found.add((PARENT, "." * level + (node.module or "")))
            elif node.module is None or (level == 0 and node.module == package):
                # ``from . import x`` and ``from etl import x`` name siblings.
                found.update((LOCAL, _sibling(etl_dir, alias.name)) for alias in node.names)
            elif level == 1:
                found.add((LOCAL, node.module))
            else:
                found.add(absolute(node.module))
    return found


def check(etl_dir: Path, filenames: frozenset[str] | None = None) -> list[str]:
    """Return one human-readable problem per offending import.

    ``filenames`` is the set of modules to check (the publication boundary in
    CI); ``None`` checks every ``*.py`` directly under ``etl_dir``. A local
    import passes only when it names one of the checked modules, so a checked
    module cannot lean on a sibling the guard never looks at.
    """
    files = (
        sorted(etl_dir.glob("*.py"))
        if filenames is None
        else [etl_dir / name for name in sorted(filenames)]
    )
    if not files:
        return [f"no Python files found under {etl_dir} - wrong path?"]

    package = etl_dir.name
    checked = {path.stem for path in files}
    problems: list[str] = []

    for path in files:
        if not path.is_file():
            problems.append(f"{path.name}: required boundary module is missing")
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            problems.append(f"{path.name}: could not read ({exc})")
            continue
        try:
            imports = resolve_imports(source, package, etl_dir)
        except SyntaxError as exc:
            problems.append(f"{path.name}: does not parse ({exc})")
            continue
        for kind, name in sorted(imports):
            if kind == STDLIB or (kind == LOCAL and "." not in name and name in checked):
                continue
            if kind == THIRD_PARTY:
                problems.append(
                    f"{path.name}: imports {name!r}, which is not in the standard "
                    f"library and not a module of api/etl."
                )
            elif kind == PARENT:
                problems.append(
                    f"{path.name}: imports {name!r}, which climbs out of api/etl "
                    f"into a parent package."
                )
            else:
                dotted = f"{package}.{name}"
                problems.append(
                    f"{path.name}: imports {dotted!r}, a module of api/etl that is "
                    f"not in the checked boundary set."
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
    problems = check(etl_dir, PUBLICATION_BOUNDARY)

    if problems:
        print("FAIL: the ETL safety boundary must import only the standard library.")
        print()
        for problem in problems:
            print(f"  {problem}")
        print()
        print("A third-party dependency in the boundary is a design decision, not a")
        print("code change: record it in docs/PUBLICATION_DECISIONS.md and remove the")
        print("module from PUBLICATION_BOUNDARY here, with the reason. Do not delete")
        print("this check. A sibling module outside the boundary set must either join")
        print("PUBLICATION_BOUNDARY (and pass this check itself) or not be imported.")
        return 1

    checked = sorted(PUBLICATION_BOUNDARY)
    print(f"OK: {len(checked)} ETL module(s) import only the standard library.")
    print("    scope: publication-authority modules only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
