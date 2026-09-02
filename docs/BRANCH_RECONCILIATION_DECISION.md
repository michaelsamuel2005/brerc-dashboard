# Branch reconciliation decision

**Decision date:** 23 August 2026  
**Decision:** protected `main` is the authoritative integration branch.  
**Superseded integration proposal:** PR #30, `integration/canonical` at
`d5a2711fd2f8e3e87ed4c632f3745cf79e2e725e`, must never be merged wholesale.

## Why `main` is authoritative

The two lines forked at `5417e772e45c7ccc932a17e76681bbf99d30ff33`.
At the decision point, `main` was
`6dfa694377492f411c23044fda2d696d105df996`: 193 commits existed only on
`main`, while 34 commits existed only on `integration/canonical`. A trial merge
reported 53 conflicted paths across the API routers, ETL, database integration,
CI, and frontend.

`main` is also the protected default branch and contains the reviewed work from
Ting Ting, Victor, Athul, and Michael, including the nightly ETL, incremental
safety behaviour, run-history dashboard, database credential separation,
sensitive-species fail-closed preflight, and mandatory ETL CI. Replacing that
tree with canonical would make reviewed team work redundant and would make the
conflict resolution itself the least-tested change in the repository.

The decision is therefore based on provenance, review history, and operational
risk—not on which branch has the word `canonical` in its name.

## What happens to PR #30

1. Preserve its exact head with the annotated tag
   `archive/integration-canonical-2026-08-23`.
2. Close PR #30 without merging it.
3. Keep the branch read-only as historical evidence until the port queue below
   is resolved; do not add new feature work to it.
4. Every adopted subsystem starts from the latest `main` and has its own pull
   request, tests, review, and merge commit.

Closing PR #30 rejects only the unsafe tree merge. It does not reject the work
or erase its authorship.

## Non-negotiable `main` behaviour

Ports must preserve these already-integrated behaviours unless a later,
explicitly reviewed decision replaces one:

- Ting Ting's nightly ETL and authenticated run-history dashboard.
- Victor's API, PostGIS, tile/deployment, query-cap, and incremental-watermark
  work.
- Incremental runs do not infer whole-database deletions from a partial window.
- A missing or invalid sensitive-species list stops before any database write.
- Database-mode source sensitivity is explicit; CSV and database semantics are
  never silently conflated.
- API read-only, ETL writer, and schema-admin credentials remain separate and
  fail closed.
- The protected CI job runs both the API and the complete ETL/safety suites.

## Approved subsystem port queue

"Approved" here means approved to prepare as a separate reviewable port. It
does not mean approved for production or exempt from component-owner review.

| Order | Subsystem | Canonical sources | Required integration rule |
| --- | --- | --- | --- |
| 1 | Publication safety core | selected parts of `333ddfc`, plus `7420158` and the view-identity fixes | Coexist with the nightly ETL; do not replace it. Keep publication blocked until BRERC approves the view and policy. |
| 2 | Trusted PostgreSQL source connector | `api/brerc_source`, connector tests, capture SQL and connector documentation from `333ddfc`, `db5cadb`, `bd01cc0`, `c8558f2`, `f2d5eca` | Read-only, TLS-verified, exact database/role/view identity; no credentials in git. |
| 3 | Initial publication store and loader | `bf7f39b`, `5c8bf2b`, `f2d5eca`, `85272bc` | Initial-only port at the time of this decision; now extended by migration 0003 and the full-snapshot refresh runbook. Preserve the deliberate incremental block. Migrations, roles, loader, atomic activation, cleanup, and live PostGIS tests travel together. |
| 4 | `serve.*` API adapter | `91cd71f`, `9368a7a`, `da85b86`, relevant part of `df9dd66` | Adapt Victor's current routers; do not replace the API package wholesale. Prove compatibility against a real activated release. |
| 5 | Publication-aware web contract and UI | `7528f1e`, `5b3092d`, `e0b31db`, `d90ef26`, `43010fb`, accessibility/e2e repair commits | Port behaviours into the current frontend in reviewable slices. Preserve accepted Athul behaviours and credit their original commits. |
| 6 | Species-media curation mechanism | `d5a2711` | Mechanism only; fail closed with no approved registry. Real descriptions, images, licences, and approvals remain external work. |

The source and loader may share a stacked review branch while being reviewed,
but they must remain separate commits with explicit source provenance. The API
cannot merge before its database contract. The web contract cannot merge before
the API response contract is fixed.

## Work deliberately not ported from canonical

- The canonical copy of the run-history dashboard: `main` already contains the
  reviewed, newer implementation.
- A wholesale replacement of `api/etl`, `api/app`, or `web`.
- Claims or code paths for genuine incremental deletion/withdrawal handling.
- Martin: canonical contains a database role, not a complete vector-tile
  service.
- Draft accessibility or privacy assertions that still require a named human
  attestation.
- Approved media content: the curation mechanism is not a licence decision.
- Production hostnames, credentials, BRERC view approval, or publication
  thresholds.

## Authorship and review rules

Each port must satisfy all of the following:

1. Start from the latest protected `main`; never rebase or merge canonical into
   it as a tree.
2. Use `git cherry-pick -x` when an original commit can move intact.
3. When a mixed commit must be split, retain its original `Author`, add a
   `Ported-from: <full SHA>` trailer, and keep compatibility work in a separate
   commit by the person performing that work.
4. Never use a blanket `ours` or `theirs` conflict resolution.
5. Preserve the existing main implementation until the replacement passes its
   own tests; do not delete another contributor's work merely to make a port
   compile.
6. Do not convert another person's idea into a `Co-authored-by` trailer without
   their consent. Link the original PR/commit and ask its author to review the
   adapted behaviour.
7. Use merge commits rather than squash merging so the ported authors and
   compatibility commits remain visible.
8. Require fresh complete CI and a formal approval from the relevant component
   owner on the final head. If `main` or the head changes, resynchronise, rerun,
   and reapprove.

## Production boundaries unchanged by this decision

This reconciliation does not provide BRERC approval. Production publication
still requires the approved live view/version, source role and environment,
publication policy and count thresholds, real-data rehearsal, controlled
deployment evidence, monitoring/outbox delivery, and the retained five-million
row scale evidence for the exact loader revision. Genuine incremental loading
remains blocked until identifier, modification-date, deletion, withdrawal, and
lookup-invalidation semantics are approved.

## Completion test

The branch decision is complete when:

- this record is merged into `main`;
- the archive tag exists at the exact PR #30 head;
- PR #30 is closed without a merge commit;
- each adopted subsystem is represented by an independent main-based PR or is
  explicitly recorded as waiting for its prerequisite/reviewer;
- no port silently weakens the non-negotiable `main` behaviours above.
