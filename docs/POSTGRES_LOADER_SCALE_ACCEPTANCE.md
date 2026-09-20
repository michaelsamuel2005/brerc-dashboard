# PostgreSQL loader scale acceptance

## Purpose and current status

The ordinary integration suite proves the loader's behaviour with small,
synthetic datasets. It cannot establish that the same implementation is
operationally viable for BRERC's expected source size of approximately five
million rows.

The manual `loader-scale-acceptance.yml` workflow is the executable scale gate.
It provisions two isolated TLS databases, generates exactly 5,000,000 synthetic
source rows with the reviewed 39-column view, and runs the concrete path:

```text
TLS PostgreSQL 16 source
  -> trusted read-only source connector
  -> bounded streaming safety transform
  -> PostgreSQL 16 / PostGIS 3.5 candidate
  -> database finalisation and reconciliation
  -> atomic initial activation
  -> active-only serving views
```

Historical evidence from the archived canonical branch does not establish the
ported implementation on protected `main`. A retained `status=passed` artifact
whose `gitCommit` is the exact loader/store merge SHA is required before the
five-million-row initial-release blocker can be closed.

## Scope limitation

The loader now supports both a first `initial` release and atomic `refresh` from
a newer complete source snapshot. The current scale harness still exercises
only the initial path described above. It **cannot prove** the runtime,
temporary-space, WAL, retained-base-release storage or atomic visibility of a
five-million-row old-release-to-new-release replacement.

Before scheduled refresh is accepted at BRERC scale, extend this manual gate to
perform a changed complete-snapshot refresh and retain a separate green
artifact. The refresh case must prove at least one update and one source removal,
the prior release remaining visible until the switch, the new release becoming
fully visible in one step, the prior release retiring, refresh thresholds being
bound in the manifest, and failure leaving the prior release active. Run it from
the **exact protected-`main` merge SHA** containing the refresh implementation;
an earlier initial-only artifact is not sufficient.

No real BRERC data is used. The generator creates deliberate synthetic cohorts:

- one unlicensed row that must be withheld;
- a two-row cell cohort that must be suppressed when `k=3`;
- three sensitive rows that must be no finer than 1 km;
- an ordinary precision control; and
- deterministic large cohorts completing the exact five-million-row total.

Private-looking sentinel text and precise coordinates are invented solely to
prove that raw fields do not cross into the destination.

## Approval before running

Configure the GitHub environment `brerc-scale-acceptance` with required
reviewers. The reviewer must confirm the run cost, runner capacity and every
budget. Do not add permissive defaults: a missing budget must prevent the run.

The workflow requires the operator to type:

```text
RUN_EXACTLY_5000000_SYNTHETIC_ROWS
```

It also requires the exact 40-character merge commit for the loader/store port.
Dispatch the workflow with `main` selected only after that commit is present on
protected `main`, and before another commit moves the branch. The validation job
refuses any non-`main` ref or any `github.sha` that differs from the supplied
merge SHA. The evidence document independently records that checked-out commit.

It also requires explicit positive limits for:

- combined failed and successful loader duration;
- finalisation, activation and pending-candidate cleanup duration;
- loader-process peak RSS;
- source and destination PostgreSQL temporary bytes;
- target WAL generation and peak observed database growth; and
- minimum free disk both before and after the workload.

The values are operational decisions, not values this repository can invent.
The combined workload budget is capped at 18,000 seconds so the six-hour job
retains one hour for provisioning and evidence upload.
They should be agreed against the intended BRERC host, backup/WAL capacity,
maintenance window and recovery objective. A run on GitHub-hosted hardware is
useful implementation evidence but is labelled non-production; BRERC-host
acceptance is still required before deployment.

## What the workflow executes

The workflow is manual-only, globally serialised and never cancels an in-flight
run. All Actions and database images are pinned to immutable commit or image
digests. Setup and synthetic row generation happen before the measured loader
window.

The runner performs two complete source reads:

1. A controlled late failure with all source licences disallowed. It injects a
   process-loss boundary after the database has durably recorded terminal
   failure, one outbox event and `cleanup_pending=true`, but before the large
   best-effort purge.
2. A successful run. The next lock owner must purge the pending failed
   candidate before it may begin, then stream, finalise and activate the exact
   five-million-row source.

This intentionally exercises roughly ten million transformed inputs. It is
expected to expose an inadequate cleanup window rather than hide it. If cleanup
cannot complete, the gate fails and the loader remains unavailable for
production until the cleanup design or approved budget is corrected.

## Required database oracles

A passing artifact means every one of these checks succeeded:

- exact source row count, non-null IDs and distinct IDs;
- fixed 5,000-row source and destination batches;
- licence withholding, 1 km sensitivity handling and whole-candidate sparse
  suppression;
- exact manifest, species, cell, species-year and withheld counts;
- candidate digest equals an independently reread database digest;
- optional row fields and individual public records remain disabled;
- synthetic raw sentinels and forbidden raw columns are absent;
- public observers saw only the empty state or a complete active state;
- failure/outbox/cleanup debt were durable before purge;
- the next owner cleared all failed payload and stage rows;
- successful activation left every staging table empty;
- PostgreSQL `fsync`, `full_page_writes` and `synchronous_commit` were enabled;
- no target table was unlogged; and
- every measured value met its operator-provided budget.

The observer does not weaken isolation or query raw/source data. Candidate
details remain invisible through the public role until activation commits.

## Evidence handling

The retained `brerc-loader-scale-evidence-<run id>-<attempt>` artifact is a
canonical JSON document containing only allow-listed aggregate counts, timings,
sampled sizes/capacity, durability settings, code/file/image/manifest digests
and boolean oracles. It contains no
rows, HMAC tokens, DSNs, hostnames, database paths, credentials or tracebacks.

The runner refuses a dirty checkout and binds the evidence to:

- the Git commit;
- the exact source generator, migration, role, runner and workflow hashes;
- the source-contract, observed-view, policy, compatibility, source-result and
  candidate/database digests;
- the runner CPU/RAM, relevant PostgreSQL settings and observed batch counts;
  and
- the pinned PostgreSQL and PostGIS image digests.

The artifact is integrity evidence for that synthetic run. It does not
authenticate BRERC approval, prove the live source view, or substitute for a
run on the controlled deployment hardware.

## Interpreting failure

Any missing metric, missing oracle, budget breach, database error, interruption
or malformed argument produces a non-zero exit and only a fixed failure code.
Never raise a budget merely to turn a red run green. Investigate the resource or
correctness cause, agree a design/budget change, and rerun from a fresh target.

Keep the production scale blocker open until all of these exist:

1. a green initial synthetic artifact reviewed by the project team;
2. a green changed-refresh synthetic artifact from the exact protected-`main`
   refresh merge SHA; and
3. comparable green initial and refresh runs on the intended BRERC-controlled
   infrastructure with approved operational limits.
