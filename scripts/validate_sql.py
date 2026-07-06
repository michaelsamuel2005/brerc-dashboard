#!/usr/bin/env python3
"""Validate every .sql file against the real PostgreSQL grammar (offline).

Uses ``pglast`` (libpg_query — the actual PostgreSQL parser) so a syntax error is
caught in CI without needing a running database. psql client-side constructs
(meta-commands like ``\\set`` and variable interpolations like ``:'var'``) are
not server SQL, so they are neutralised before parsing.

Run: ``python scripts/validate_sql.py``  (exit non-zero on any parse failure).
"""

from __future__ import annotations

import glob
import re
import sys

try:
    import pglast
except ImportError:  # pragma: no cover
    sys.exit("pglast is required: pip install pglast")


def neutralise_psql(sql: str) -> str:
    """Strip psql meta-commands and substitute variable interpolations."""
    # Drop whole meta-command lines (\set, \if, \echo, \endif, \i, ...).
    lines = [ln for ln in sql.splitlines() if not ln.lstrip().startswith("\\")]
    cleaned = "\n".join(lines)
    # :'name' -> a quoted literal;  :{?name} -> TRUE (used only inside \if, already gone).
    cleaned = re.sub(r":'[A-Za-z_][A-Za-z0-9_]*'", "'x'", cleaned)
    cleaned = re.sub(r":\{\?[A-Za-z_][A-Za-z0-9_]*\}", "true", cleaned)
    return cleaned


def main() -> int:
    files = sorted(glob.glob("db/**/*.sql", recursive=True))
    if not files:
        print("No .sql files found under db/.")
        return 1
    failures = 0
    for path in files:
        with open(path, encoding="utf-8") as handle:
            source = neutralise_psql(handle.read())
        try:
            pglast.parse_sql(source)
            print(f"OK   {path}")
        except Exception as exc:  # noqa: BLE001 - report any parse error
            failures += 1
            print(f"FAIL {path} -> {str(exc)[:160]}")
    print("---", "all SQL valid" if not failures else f"{failures} file(s) failed to parse")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
