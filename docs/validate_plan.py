#!/usr/bin/env python3
"""
Validate docs/PLAN.yaml — the machine-readable BRERC front-end build plan.

This is deliberately dependency-light and CI-friendly: it exits non-zero on the
first failed invariant so it can gate a pipeline or be run by another agent to
confirm the plan is internally consistent before trusting it.

Usage:
    python docs/validate_plan.py            # validate docs/PLAN.yaml
    python docs/validate_plan.py path.yaml  # validate a specific file

Requires: pyyaml, jsonschema  (pip install pyyaml jsonschema)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
PLAN = Path(sys.argv[1]) if len(sys.argv) > 1 else DOCS / "PLAN.yaml"
SCHEMA = DOCS / "plan.schema.json"

MUST_REQUIREMENTS = {f"R{i}" for i in range(1, 9)} | {"C1", "C2", "C3"}
# C2 plan-level lint: every client-facing endpoint must PROMISE (via excludesFields)
# to withhold these PII / precise-coordinate / re-identification fields. This checks
# the contract's declared intent — the runtime enforcement is the contract tests and
# CI grep-guard on REAL payloads described in the plan (P1-S5, P3-S4, P6.5, P7).
CORE_EXCLUDED = {"recorder1", "bliss", "eastings", "northings", "comments", "sensitivity"}

failures: list[str] = []
checks: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append(name)
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(f"{name}: {detail}" if detail else name)


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("pyyaml is required: pip install pyyaml", file=sys.stderr)
        return 2

    # --- 1. YAML parses ---
    try:
        plan = yaml.safe_load(PLAN.read_text(encoding="utf-8"))
        check("YAML parses", True, str(PLAN))
    except Exception as ex:  # noqa: BLE001
        check("YAML parses", False, str(ex))
        return 1

    # --- 2. Conforms to JSON Schema ---
    if SCHEMA.exists():
        try:
            import jsonschema

            jsonschema.validate(plan, json.loads(SCHEMA.read_text(encoding="utf-8")))
            check("Conforms to plan.schema.json", True)
        except ImportError:
            check("Conforms to plan.schema.json", True, "SKIPPED (install jsonschema to enable)")
        except Exception as ex:  # noqa: BLE001
            check("Conforms to plan.schema.json", False, str(ex)[:160])
    else:
        check("Conforms to plan.schema.json", True, "SKIPPED (schema file absent)")

    # --- 3. Requirement coverage ---
    reqs = {r["id"] for r in plan.get("requirements", [])}
    missing = MUST_REQUIREMENTS - reqs
    check("All R1-R8 + C1-C3 present", not missing, f"missing {sorted(missing)}" if missing else "")

    # --- 4. Referential integrity of requirement ids on phases/steps ---
    phases = plan.get("phases", [])
    phase_ids = [p["id"] for p in phases]
    covered: set[str] = set()
    bad_refs: list[str] = []
    subset_violations: list[str] = []
    for p in phases:
        phase_reqs = set(p.get("requirementIds", []))
        covered |= phase_reqs
        step_union: set[str] = set()
        for s in p.get("steps", []):
            sids = set(s.get("requirementIds", []))
            step_union |= sids
            covered |= sids
            for rid in sids:
                if rid not in reqs:
                    bad_refs.append(f"{s.get('id')}->{rid}")
        # every step's requirements should be declared at phase level too
        if not step_union <= phase_reqs:
            subset_violations.append(f"{p['id']} steps add {sorted(step_union - phase_reqs)}")
    check("No step cites an unknown requirement id", not bad_refs, ", ".join(bad_refs))
    check("Step requirements ⊆ phase requirements", not subset_violations, "; ".join(subset_violations))

    r_only = {f"R{i}" for i in range(1, 9)}
    uncovered = r_only - covered
    check("Every R1-R8 appears in >=1 phase/step", not uncovered, f"uncovered {sorted(uncovered)}" if uncovered else "")

    # --- 5. dependsOn is a valid DAG referencing real phases ---
    edges = {p["id"]: p.get("dependsOn", []) for p in phases}
    unknown = [f"{pid}->{d}" for pid, deps in edges.items() for d in deps if d not in phase_ids]
    check("dependsOn references only real phases", not unknown, ", ".join(unknown))

    color: dict[str, int] = {p: 0 for p in phase_ids}  # 0 white, 1 grey, 2 black
    cyclic = {"v": False}

    def dfs(u: str) -> None:
        color[u] = 1
        for v in edges.get(u, []):
            if v not in color:
                continue
            if color[v] == 1:
                cyclic["v"] = True
            elif color[v] == 0:
                dfs(v)
        color[u] = 2

    for pid in phase_ids:
        if color[pid] == 0:
            dfs(pid)
    check("dependsOn is acyclic (DAG)", not cyclic["v"])

    # --- 6. C2 net: every client endpoint promises to exclude the core PII/coord fields ---
    contract = plan.get("apiContract", {})
    endpoints = contract.get("endpoints", contract) if isinstance(contract, dict) else contract
    ep_list = list(endpoints.values()) if isinstance(endpoints, dict) else (endpoints or [])
    gaps: list[str] = []
    for ep in ep_list:
        if not isinstance(ep, dict):
            continue
        name = ep.get("endpoint", "?")
        excludes = {str(x).lower() for x in ep.get("excludesFields", [])}
        missing = CORE_EXCLUDED - excludes
        if missing:
            gaps.append(f"{name} omits {sorted(missing)}")
    check("Every client endpoint excludesFields ⊇ core PII/coord set (C2)", not gaps, "; ".join(gaps))

    print()
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed.")
    if failures:
        print("PLAN VALIDATION FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("PLAN VALIDATION PASSED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
