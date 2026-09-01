# `api/etl` — the public-data safety boundary

Turns raw BRERC records into policy-filtered aggregate payloads for the public API.
**Nothing here may emit a location finer than the publication policy allows.**

The selected **safe-v1** boundary withholds every record classified as sensitive before a
public geometry or public identifier is created. Sensitivity is the union of the retained taxon
snapshot, the digest-bound species dictionary, the source row flag and approved sensitive
record-type rules. Ordinary records may contribute only at 1 km or coarser, and a coarser source
record is never sharpened. Safe v1 is aggregate-only and uses `min_records_per_cell=1`, which
means no additional minimum-count suppression after the safety gate.

The mechanism is implemented and tested in this repository. That is not a claim that a real-data
release is active: production still requires the retained version-2 policy artifact, its exact
live inputs and the operational evidence listed below.

```bash
cd api && python3 -m unittest discover -s tests -t . -p 'test_*.py'
```

The publication safety modules listed below are **standard-library only** — no
pandas and no third-party runtime dependency. The existing nightly ETL remains
in this package as `nightly_pipeline.py` and its established subpackages; it is
not used as publication authority by the trusted connector or release loader.
`scripts/guard_stdlib_only.py` pins the exact boundary file set so the two paths
can coexist without making a false package-wide dependency claim.

## Modules

| File | Purpose |
|---|---|
| `gridref.py` | Parse OS grid references, derive precision, coarsen to a larger square |
| `policy.py` | **BRERC's publication decisions, as a versioned, approvable object** |
| `sensitivity.py` | The multi-axis sensitivity gate: **withhold or generalise only as the explicit policy says** |
| `contract.py` | Public allow-list types; verified-status parity with the client |
| `aggregate.py` | Species + year + grid-cell aggregation, with an auditable report |
| `pipeline.py` | The whole boundary. Explicit column mapping, nothing inferred |
| `source_contract.py` | Exact live-view schema, safety mapping and load-mode preflight |
| `identifiers.py` | Canonical private source identifiers and duplicate detection |
| `species.py` | Authoritative species-id checks and safe dictionary resolution |
| `../tests/test_verified_parity.py` | Shared verdict corpus, also used by the browser tests |
| `cleaning.py` | Exploratory only — **not** the boundary |
| `filtering.py` | Superseded shim; raises rather than reverting to drop semantics |

## The policy object is the point

Every decision that changes what the public can see lives on `PublicationPolicy`, not in
our constants. Resolutions, place names, record ids, suppression thresholds, licensing,
the treatment of unresolved taxa — none of these are engineering choices, and several are
irreversible once published.

```python
from etl.pipeline import ColumnMap, build_candidate_payloads, run_pipeline_for_source
from etl.policy import PublicationPolicy
from etl.sensitivity import SENSITIVE_SNAPSHOT_SHA256, SENSITIVE_SNAPSHOT_VERSION
from etl.source_contract import BRERC_MAIN_DATA_DASH, LoadMode

# Safe-v1 decision envelope. This example is not a production artifact: real
# approval/evidence values and exact retained bytes must be supplied externally.
policy = PublicationPolicy(
    version="brerc-2026-08",
    precision_mode="approved",
    suppression_mode="none",
    # External fact, not an engineering default: use an evidenced allow-list,
    # or "not-applicable" only when the retained authority expressly says so.
    licensing_mode=approved_licensing_mode,
    allowed_licence_values=approved_licence_allow_list,
    record_type_safety_mode="rules",
    row_level_records_mode="aggregates-only",
    verification_publication_mode="unavailable",  # view has no verdict column
    sensitive_record_action="withhold",
    ordinary_resolution_metres=1000,
    map_cell_resolution_metres=1000,
    min_records_per_cell=1,                # k=1: no additional sparse-cell suppression
    default_sensitive_metres=10000,        # retained policy metadata; no safe-v1 sensitive row emits
    row_sensitive_resolution_metres=1000,  # classification metadata; the row is withheld
    non_sensitive_values=frozenset({"no"}),
    sensitive_record_type_metres=approved_sensitive_record_type_rules,
    record_type_vocabulary=approved_record_type_vocabulary,
    sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
    sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
    # At least 32 random bytes, supplied by a secret store; never in the repo.
    public_id_salt=os.environ["BRERC_PUBLIC_ID_SECRET"],
)

# Direct approval uses policy.with_approval(...). If BRERC delegated authority,
# use policy.with_delegated_approval(...): name the actual approver and their
# organisation as well as the BRERC delegator, delegation scope/date and the
# separately retained delegation evidence. Do not label a delegate as BRERC.

records, report = run_pipeline_for_source(
    rows,
    columns,
    source_contract=BRERC_MAIN_DATA_DASH,
    source_metadata=source_metadata,
    source_result_columns=source_result_columns,
    load_mode=LoadMode.INITIAL,
    policy=policy,
    dictionary=dictionary,
)
preview = build_candidate_payloads(records, report)
```

That final value is a **development/QA preview**, not a public release. The confirmed BRERC
contract pins column metadata but does not yet contain an approved identity for the view SQL,
so `build_payloads(...)` deliberately refuses it. A future reviewed contract must pin that
identity before the release path can succeed.

Production loading accepts only exact JSON with
`artifactFormat="brerc-publication-policy/v2"`. Version 2 binds
`sensitiveRecordAction` and the direct/delegated approval chain into the approval digest; a
version-1 artifact is rejected rather than being assigned the new decision implicitly.

Three guards make this more than documentation:

* **There is no default policy anywhere.** `generalise()` and `run_pipeline()` both require
  one. A default would mean a caller who forgot it still got a run — and a silent 100%
  withhold reads in the report like a data problem rather than a missing decision.
* **`validate()` runs before the first row.** A policy naming a resolution the client cannot
  draw, or with no way to derive a public record id, is a configuration error and fails as
  one. It does not fail one record at a time, deep inside the gate.
* **`DEVELOPMENT_POLICY` can never report itself approved.** `development_only=True` makes
  `is_approved()` False and `assert_approved()` raise, whatever else is set on it — including
  via `dataclasses.replace`. A development policy that satisfies the production guard defeats
  the guard entirely.

`UNAPPROVED_POLICY` is the null policy. It does not publish little — `validate()` **refuses**
it, so the pipeline cannot run under it at all. Choosing what the public sees must be an act,
not an omission.

## Defects these modules fix

**1. Coarsening is not string truncation.** `ST587721` is easting `587`, northing `721`.
Generalising to 1 km keeps two digits *per axis* → `ST5872`. Truncating the string gives
`ST5877` — a different square, 500 m away. That would have silently relocated every
generalised record, including protected species, and it looks correct on review.
Pinned by `test_naive_string_truncation_would_be_wrong`.

**2. Historical drop and generalisation behaviours are not the safe-v1 decision.** The old
`filtering.py` silently removed sensitive species; a later development policy generalised them
to coarser squares. Both histories matter when reading old evidence, but neither is allowed to
choose current production behaviour implicitly. `PublicationPolicy.sensitive_record_action`
now makes the decision explicit. Safe v1 chooses `withhold`, records the fixed
`sensitive-record-withheld` disposition and does so before geometry and public-id generation.

**3. Safe v1 has one public location tier.** Older prototype contracts accepted individual
records at 100 m and map cells at 1 km. Safe v1 publishes aggregates only: an otherwise eligible
ordinary record contributes at **1 km or coarser**, and a coarser source record is retained at
its honest source precision. The browser's ability to parse 100 m is not permission to publish
real BRERC data at 100 m.

**4. The column name was hard-coded and guessable.** `df["species_id"]` raises a KeyError on
the real data — fail-closed, survivable. But the tempting fix is a `.get()` or a try/except,
which turns it **fail-open** with nothing gated. `pipeline.ColumnMap` requires every source
column explicitly and raises `MissingColumns` before any row is processed.

**5. Dates are `DD/MM/YYYY`, not ISO.** `_to_year` took the first four characters, so
`"23/03/2023"` → `int("23/0")` → `ValueError`. **0 of 998** varied rows and 6 of 918 reptile
rows would have produced a year; every record would have been withheld as `unusable-year` and
the report would have called it normal operation. Now takes the last plausible 4-digit group,
so `"04/08/2023 - 17/10/2023"` → 2023 (the end year, matching the source's own `YearEnd`).

**6. A BRERC species number is not an integer.** **61,080 of 96,824** dictionary entries are
alphanumeric — `BRERC10469`, `6973a`, `Z5567`, `5519a`, `25913A`. `int(species_id)` raised on
all of them and fell through to fail-closed, needlessly generalising **50 of 998** ordinary
varied records to 10 km. Safe, but it would have destroyed the precision of most invertebrate
records on the full dataset. Ids are compared as normalised strings.

**7. The occurrence export has no species-id column at all.** Both samples carry only
`Scientific_Name` / `Common_Name`, while sensitivity is keyed on `SPECIES_NO` in the
dictionary. The gate therefore *cannot* run on an occurrence row alone. `species.py` makes
that join part of the pipeline; an unresolved name fails closed.

**8. A well-formed id absent from the taxonomy was published as ordinary.** That is fail-open:
any unrecognised numeric id reached the public tier at the ordinary resolution. `known` is now
established by the dictionary join, and `unknown_species_action` decides — `"withhold"` or
`"coarsest"`. There is deliberately **no `"ordinary"` option**, and `validate()` rejects one.

**9. A negated acceptance was read as accepted.** `"Not accepted"` contains `"accept"` and no
`"reject"`. Against the 63-case shared corpus the old client function produced **10 false
accepts** and returned `"unknown"` for 26 legible verdicts. Both implementations now test
negation before acceptance; `api/tests/test_verified_parity.py` and `web/src/lib/api/verified.test.ts`
pin the identical corpus.

**10. `pageSize` could be 0.** `RecordPageSchema.pageSize` is `z.number().int().positive()`,
and an earlier `build_payloads` used `len(records)` — so an empty result set failed client
validation and rendered as a *network error* rather than an empty state.

**11. A tetrad was withheld even when a safe coarser square existed.** `coarsen()` returned
None for every tetrad, so a tetrad record was lost as `cannot-generalise` even though its own
10 km square was sitting in the reference. A tetrad is exactly contained in its 10 km square,
so dropping the letter is arithmetically exact. It matters: tetrads are standard in UK
botanical recording, and **54 of the 65 taxa on BRERC's sensitive list are plants**.

**12. Suppression was applied to the map only.** Hiding a sparse cell while still listing its
records in the table, and counting them in the year series, does not suppress anything — the
same information is one click away. Records inside a suppressed cell are now withheld, and
cells and the year series are rebuilt from the survivors, so map, table, chart and totals
describe one dataset.

**13. Original BRERC record numbers were published verbatim.** They are reversible back to the
source row. `PublicationPolicy.public_record_id` derives a non-reversible id (HMAC-SHA256 with
a cryptographically random key kept out of the repository, truncated to 128 bits). The key
must be at least 32 bytes, is excluded from policy logs/repr, and `run_pipeline` still asserts
uniqueness within a run so any collision is a loud failure rather than two records merging.

**14. `describe_dataset` printed record content.** The original `clean_data` printed
`df.head()`, putting real grid references, place names, recorder attributions and comments
into stdout — and therefore into CI logs, terminal scrollback and any log aggregator. It now
returns a structural summary and prints nothing.

## How the boundary keeps PII out

**Allow-list, not deny-list.** `PublicRecord` and `PublicCell` have no field for a recorder
name, precise coordinate, comment or sensitivity marker. Output is *constructed* field by
field; no source row is ever passed through. A deny-list misses the column nobody thought of
— a new export adds `Recorder2`, a supplier renames `Comments` to `Notes`. An allow-list
cannot leak a field it has no slot for.

`assert_no_forbidden_fields()` mirrors the `FORBIDDEN` set in
`web/src/lib/api/contract.test.ts` as belt and braces. If it ever fires, the allow-list has
been bypassed and *that* is the bug.

Place names are withheld unless `policy.publish_place_names` is set. A place can defeat
generalisation entirely: a 10 km square beside *"Private garden, 12 Acacia Avenue"* is not
generalised in any useful sense.

## Fail-closed behaviour

Every withheld record carries a reason, and every input row is accounted for **exactly** —
`PipelineReport.reconciles()` is `==`, not `<=`. An inequality passes while rows vanish, which
is the failure the report exists to detect.

| Reason | Cause |
|---|---|
| `sensitive-record-withheld` | Safe-v1 classification found sensitivity on the taxon snapshot, dictionary flag, source row or approved record type |
| `species-not-permitted` | Taxon did not resolve, and the policy withholds unknowns |
| `missing-grid-ref` | No reference on the record |
| `unparseable-grid-ref` | Not a valid OS reference, or an odd digit count |
| `resolution-not-public` | Own resolution is real but undrawable — a **tetrad** or a 100 km reference |
| `cannot-generalise` | Target unreachable by positional truncation |
| `finer-than-required` | Belt-and-braces check; should be unreachable |
| `licence-not-permitted` | Licence absent or outside BRERC's stated vocabulary |
| `suppressed-sparse-cell` | Cell fell below `policy.min_records_per_cell` |
| `unusable-year` | Missing, unparseable, or outside 1500–2200 |
| `missing-scientific-name` / `missing-record-id` | Required field absent |

An unusable or absent species id is treated as **sensitive**, not ordinary. The dictionary's
own `SENSITIVE` flag is **unioned** with our retained 65-id snapshot, never substituted for
it — a union can only over-protect, so a stale or partly-loaded dictionary cannot silently
unprotect a taxon.

## Emittable resolutions — one source of truth

`gridref.PUBLIC_RESOLUTIONS_METRES = (100, 1000, 10000)` records what
`web/src/lib/geo/gridref.ts` can parse and draw. `policy.py` aliases that tuple rather than
restating it, and `validate()` rejects any policy naming a resolution outside it.

Two resolutions are deliberately absent because the client regex `^[A-Z]{1,2}(\d+)$` rejects
them, so emitting either produces a square the client silently fails to draw:

* **2 km (tetrad)** — the trailing letter is rejected.
* **100 km (letters only)** — `"ST"` has no digits.

A record whose *own* resolution is one of these is withheld as `resolution-not-public`.
`policy.coarsen_unpublishable_resolutions` (default **False**) would instead promote it to the
next drawable square — 2 km → 10 km, strictly coarser so it cannot disclose more, but a
different presentation. Safe v1 keeps this switch false and withholds the input; enabling it
later requires a new policy version.

## Safe-v1 resolution behaviour

Safe v1 emits no sensitive record and therefore has no sensitive 10 km cell. Ordinary records
aggregate at 1 km unless their source reference is already coarser; in that case the source
precision is kept because the pipeline must never invent finer knowledge. `GridCellSchema`
carries `precisionMetres` per cell and the client derives the polygon from the grid reference.

Older development evidence may show sensitive rows generalised into mixed-resolution cells.
That remains a supported, explicitly selectable policy mechanism for a future approved policy,
but it is **legacy/development behaviour, not safe v1**.

## Historical real-subset verification (28 Jul 2026; rerun required)

Run against `varied sample from main5.xls` (998 rows) and `reptile sample from main5.xls`
(918 rows), with the full 96,824-row species dictionary and the 155-row record-type list.
This used the former development/generalisation policy, not safe v1.

| Check | Result |
|---|---|
| Grid references parsed by `gridref.py` | **1,916 / 1,916 (100%)** |
| Names resolved to a species number | **1,916 / 1,916 (100%)**, 553/553 distinct |
| Records published | 1,916 — none withheld; reconciles exactly |
| Precision **before** the gate | reptile: 1 m ×200, 10 m ×533, 100 m ×172, 1 km ×13 |
| Precision **after** the gate | 100 m ×1,903, 1 km ×13 — **nothing finer** |
| Public record ids in that run | 1,916 distinct, 16 hex chars, no original id present anywhere |
| Place names in output | **none** |
| Forbidden fields in output | **none** |
| Every record validated against the frontend's real Zod schemas | **`CellDistributionSchema` (272 cells) and `RecordPageSchema` (1,916 records) both PASS** |

The reptile sample contains **200 records at 1-metre precision** and 533 at 10 m. The gate
coarsens every one to 100 m. Precise locations are routine in the source: the gate is
load-bearing, not a formality.

That run predates the reviewed source-view contract, approval binding and the move to 128-bit
(32-hex-character) public ids. Its input-quality evidence remains useful, but it is **not** a
current release sign-off. It must be repeated after BRERC approves a publication policy and
before any real-data release.

**Historical generalisation test only:** the gate was also exercised under the former
development action against all 65 retained sensitive taxa, crossed with seven grid-reference
shapes. That 455-case run emitted 390 at 10 km and withheld 65 undrawable 100 km cases. It does
not evidence the selected safe-v1 action. Under safe v1, all 455 sensitive cases must instead
receive `sensitive-record-withheld` before a public grid reference or identifier is created;
the automated safety tests enforce that invariant.

> **The samples themselves cannot exercise the sensitive-species gate.** Neither contains a
> listed taxon — the list is 54 plants, 8 moths, a lichen, a crustacean and a mammal; the
> samples are 6 reptiles and ~547 invertebrates. One genus is shared (*Allium*). Ask BRERC for
> a sample containing known sensitive records, ideally with the expected output resolution
> stated, so the gate can be asserted end to end rather than inspected.
>
> **Nor do they contain a tetrad, a 100 km reference, or a sensitive record type.** Those
> paths are proven by unit tests only.

## Real column names (from the client export)

```
Scientific_Name  Common_Name  Grid_Ref  Place  Date_of_Record  Abundance  Sex_Stage
Record_Type  Precise_Date*  Vague_Date  vitality  verified  YearEnd  Comments*
Source  unique_No  licence  Eastings*  Northings*
```
`*` = forbidden on the public tier. `Comments` carries recorder attributions
(`per`/`det.`/`by`) in **469 of 725** reptile rows — it is PII-bearing and has no slot in
`PublicRecord`.

```python
ColumnMap(record_id="unique_No", species_id="SPECIES_NO",   # resolved via species.py
          scientific_name="Scientific_Name", grid_ref="Grid_Ref", year="YearEnd",
          common_name="Common_Name", place="Place", abundance="Abundance",
          record_type="Record_Type", verified="verified", source="Source",
          licence="licence")
```

## The second sensitivity axis: record type

`drop down lists.xls` contains **155 named record types**, but it is not yet a safe
production rule source. Only **47** named types have an aligned `sensitive = yes` value;
one `yes` has no corresponding type, and one named raptor-or-owl-nest type has no aligned
flag. Sensitivity can attach to the **record type**, not only the species, but BRERC must
correct and approve the complete versioned classification before release.

The gate now checks it: `policy.sensitive_record_type_metres` maps a lower-cased record type
to a protection rule and a listed type marks the record sensitive independently of the taxon
and source-row flag. Under safe v1, that classification withholds the row before any public
geometry or identifier is formed; the configured metres remain approval-bound metadata for
future policies but do not make a safe-v1 sensitive row publishable. Neither supplied sample
contains a positive sensitive record type, so the mechanism is proven by synthetic tests; a
controlled real example is still required for production acceptance.

## What the ETL cannot yet produce

`build_payloads` emits `CellDistributionSchema` and `RecordPageSchema` exactly, and asserts
their key sets before returning (both are `.strict()`, so a stray key is a hard parse failure
in the browser, not a harmless addition). It does **not** produce `SummarySchema`, and this is
deliberately not faked:

Individual record output is **off by default**. It is available only when the approved policy
selects `row_level_records_mode="publish"` and sets `publish_individual_records=True`;
place, abundance, record type, original identifiers and verification capabilities are bound
separately in the approval envelope. Distribution cells and year totals remain available from
aggregates, so an accessible aggregate table does not depend on publishing individual
occurrences.

* `topGroups` needs a taxonomic grouping the occurrence export does not carry. The dictionary
  has `FAMILY` and `TAXANB`; which one BRERC means by "group", if either, is not settled.
* `coverageCaveat` is text BRERC must write, not text we may invent.

`yearRange` is nullable in the current browser contract and the ETL represents an empty result
honestly. Verification now has an explicit policy mode. Under `unavailable`, record verdicts
and aggregate `verifiedCount` values are omitted even if a source column later appears; the
browser receives `verificationAvailable: false`, and species detail uses `verifiedCount: null`.
Under `publish`, production requires both a mapped verdict column and a nonempty BRERC-approved
acceptance vocabulary. That approves aggregate verification only. Per-occurrence verdicts remain
withheld unless the same policy separately sets `publish_record_verification=True` while
individual rows are enabled; aggregate counts never switch row verdicts on implicitly.

Derived figures live under `payloads["meta"]`, outside the contract shapes, precisely so
nothing can drift into a strict schema by accident.

## What is decided for safe v1

The safe-v1 decision set is deliberately narrow:

1. publish aggregates only; individual occurrences and their optional fields remain off;
2. withhold every sensitive record, whether sensitivity comes from the retained taxon snapshot,
   digest-bound dictionary, source row or approved record type;
3. publish otherwise eligible ordinary records at 1 km or their coarser source precision;
4. use `min_records_per_cell=1` and `suppression_mode="none"`, so there is no additional
   sparse-cell threshold after the safety gate;
5. withhold unresolvable taxa and unrenderable grid references; and
6. never publish original BRERC identifiers, private coordinates, place names or raw source text.

These choices remove the need to invent per-sensitive-taxon public resolutions for the first
release: sensitive records do not reach aggregation at any resolution. A future decision to show
them in coarse cells is a new policy version and needs new impact modelling and approval.

## Production inputs and evidence still required

Implemented code is not production activation. Before a real BRERC run, operators must retain
and verify all of the following:

1. the exact `brerc-publication-policy/v2` JSON bytes and SHA-256, with the safe-v1 decisions,
   approval dates and evidence reference;
2. either a direct BRERC approver, or a delegated approval that identifies the actual approver
   and organisation **and** the BRERC delegator, role, scope, delegation date and retained
   delegation evidence;
3. the approved live-view identity capture and independently pinned environment/role evidence;
4. the exact species dictionary and corrected record-type classification bound to the policy;
5. the record-data licence codebook or an evidenced `not-applicable` decision for aggregate
   display—blank source licence values are not permission;
6. a controlled sample containing genuinely sensitive rows on each available sensitivity axis,
   with expected withholding outcomes, followed by the real BRERC acceptance run;
7. production source-count/drop bounds and the evidence from the exact candidate snapshot;
8. protected public-id and reconciliation HMAC secrets, destination TLS identity and ownership;
   and
9. an approved source-view version with modification/deletion semantics before incremental mode
   can be enabled.

## Implemented mechanism and remaining operational work

The source-view preflight in `source_contract.py` pins the 39-column
`dashboard.main_data_dash` schema, validates database metadata and zero-row cursor headers,
canonicalises `unique_no numeric(13,2)`, binds the row sensitivity column and refuses
incremental mode with named blockers. Safe v1 interprets every value except explicit `No` as
sensitive and withholds that row; the old description of this field as a public 1 km route is
historical context, not current output behaviour. See `docs/SOURCE_CONTRACT.md`.

The live-view identity capture/approval workflow, trusted locked PostgreSQL connector,
streaming safety transformation, inactive PostGIS candidate loader, immutable release evidence,
database reconciliation and atomic activation mechanism are implemented in this integrated
codebase. `run_pipeline` still separates a non-serialisable `CandidatePreview` from the
release-gated payload builder, and the loader accepts only a strict approved version-2 artifact.

Migration `0002_sensitive_record_action` records `generalise` or `withhold` on both the immutable
release manifest and public-release capability row, with a deferred database constraint proving
they match. The API can therefore report the action belonging to the active release rather than
claiming a static privacy rule.

None of those mechanisms supplies the missing live BRERC capture, approval artifact, dictionary,
record-type list, licence decision, credentials, secrets, production PostGIS/TLS target or real
acceptance evidence. No production activation is claimed. Incremental update/deletion handling,
Martin (or a formally approved alternative), operational deployment/monitoring, and licensed
production content remain separate delivery decisions.
