# BRERC Public Dashboard — Implementation Plan (reader's guide)

This folder holds the **machine-readable build plan** for the BRERC public
dashboard **front-end** (the React app in `web/`). It is written for other tools
and agents to parse and validate, not just for humans.

> **Scope:** this plan covers Michael Samuel's area — the public front-end in
> `web/`. The backend API + PostgreSQL/PostGIS are owned within the 5-person team
> and appear here only as a **flagged dependency** (`assumptions[]` +
> `apiContract[]`). The internal staff dashboard (**R8**) is a deliberately
> **deferred, secondary** phase. Public-first (**R1–R7 before R8**) is mandatory.

> **Status: DRAFT.** Several design points depend on answers from BRERC
> (Tim Corner) and the team — see `openQuestions[]` in `PLAN.yaml`. Treat the
> brief's feature list as *candidates, not commitments* (constraint **C1**);
> scope is refined **with** BRERC.

## Files

| File | What it is | Authority |
|------|------------|-----------|
| **`PLAN.yaml`** | The plan: requirements, assumptions, ground-truth data facts, architecture, proposed API contract, ordered phases → steps, cross-cutting DoD gates, risks, timeline, open questions, and a self-describing `validationContract`. | **Source of truth.** |
| **`plan.schema.json`** | JSON Schema (draft 2020-12) describing the plan's structure. | Structural contract. |
| **`PLAN.json`** | JSON twin of `PLAN.yaml` for strict machine consumers. | **Generated — do not hand-edit.** |
| **`validate_plan.py`** | Runnable validator (see below). | CI gate. |

## How to validate (prove it, don't trust it)

```bash
pip install pyyaml jsonschema
python docs/validate_plan.py        # exits non-zero on any failed invariant
```

The validator checks, independently of the plan's own claims:

1. `PLAN.yaml` parses as YAML.
2. It conforms to `plan.schema.json`.
3. Every `R1–R8` + `C1–C3` requirement is present.
4. No step cites a requirement id that doesn't exist.
5. Each step's requirements are a subset of its phase's requirements.
6. Every `R1–R8` appears in at least one phase/step (no dropped requirement).
7. `dependsOn` references only real phases and forms a **DAG** (no cycles).
8. Every client-facing API endpoint's `excludesFields` covers the core
   PII/coordinate set (`Recorder1, BLISS, Eastings, Northings, Comments,
   sensitivity`) — a plan-level **C2** net. (Runtime C2 enforcement is the
   contract tests + CI grep-guard on real payloads, per phases P1/P3/P6.5/P7.)

`PLAN.yaml`'s own `validationContract.rules` list additional machine-checkable
assertions specific to this plan.

## Reading order

`meta` → `requirements` → `assumptions` + `openQuestions` (what's still unknown)
→ `architecture` + `apiContract` (the boundary) → `phases` (the build, ordered
`P0 … P8`) → `crossCuttingGates` + `risks` → `validationContract`.

## How this plan was produced

Grounded in: the 180DC/BRERC project brief, both master prompts
(`CLAUDE.md` engineering + the companion strategy prompt), the **real 19-column
`main5` sample-data schema**, and the actual repo state. It was drafted from four
independent lenses (coverage, delivery, risk, architecture), synthesised, then
put through four adversarial critics (requirement coverage, feasibility,
data/security fidelity, machine-validatability) whose blocker/major findings were
all resolved before finalising. Regenerate or amend by editing `PLAN.yaml` and
re-running the validator; keep `PLAN.json` in sync (`docs/validate_plan.py` reads
`PLAN.yaml`, so that is the file to change).
