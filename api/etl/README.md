# `api/etl` — the public-data safety boundary

Turns raw BRERC records into the aggregated, generalised payloads the public API serves.
**Nothing here may emit a location finer than the publication policy allows.**

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
| `sensitivity.py` | The sensitive-species gate: **generalise, never silently drop** |
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

# PROPOSED conservative envelope only. These values are not BRERC-approved and
# must not be copied into production until the sign-off record is complete.
policy = PublicationPolicy(
    version="brerc-2026-08",
    precision_mode="approved",
    suppression_mode="none",               # only after BRERC chooses it
    licensing_mode="not-applicable",        # only after BRERC chooses it
    record_type_safety_mode="not-used",     # only if row sensitivity includes type
    row_level_records_mode="aggregates-only",
    verification_publication_mode="unavailable",  # view has no verdict column
    ordinary_resolution_metres=1000,       # proposed; NOT BRERC-approved
    default_sensitive_metres=10000,        # BRERC MUST confirm, per taxon
    row_sensitive_resolution_metres=1000,  # BRERC MUST confirm
    non_sensitive_values=frozenset({"no"}),
    sensitive_snapshot_version=SENSITIVE_SNAPSHOT_VERSION,
    sensitive_snapshot_sha256=SENSITIVE_SNAPSHOT_SHA256,
    # At least 32 random bytes, supplied by a secret store; never in the repo.
    public_id_salt=os.environ["BRERC_PUBLIC_ID_SECRET"],
).with_approval(
    approved_by=os.environ["BRERC_POLICY_APPROVER"],
    approver_role=os.environ["BRERC_POLICY_APPROVER_ROLE"],
    approver_organisation="BRERC",
    evidence_reference=os.environ["BRERC_POLICY_EVIDENCE_REFERENCE"],
    approved_on=os.environ["BRERC_POLICY_APPROVED_ON"],
    review_due=os.environ["BRERC_POLICY_REVIEW_DUE"],
)

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

**2. Sensitive species were dropped, not generalised.** The old `filtering.py` removed them.
Safe from disclosure, so nobody caught it — but it contradicts
`Data_Governance_and_Compliance.md` (*"Generalise, do not randomise"*) and quietly destroys
data. A public map that omits protected species shows a false distribution with no indication
anything is missing. `sensitivity.generalise()` coarsens instead.

**3. The public floor was wrong.** An earlier draft used 1 km. The app has **two tiers**:
individual records at a **100 m** contract limit (`PUBLIC_MIN_PRECISION_METRES` in
`web/src/lib/api/schemas.ts`), and map cells aggregated to **1 km**. A 1 km floor would have
destroyed the precision the records table exists to show. Note the 100 m figure is a *contract
limit, not an authorisation* — whether BRERC permits 100 m publication of real locations is
still unconfirmed, which is why it now comes from the policy.

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
resolution BRERC did not choose. **BRERC's decision, listed in the questions below.**

## Mixed-resolution map cells

A sensitive record generalised to 10 km cannot be placed in a 1 km cell without inventing
precision. So cells are emitted at **mixed resolutions**: ordinary records aggregate to 1 km,
sensitive ones keep their coarser square. `GridCellSchema` carries `precisionMetres` per cell
and the client derives each polygon from the id, so a 10 km cell draws as a 10 km square —
honest, and the NBN/GBIF presentation.

> **Frontend note:** the current fixtures hardcode `precisionMetres: 1000` for every cell, so
> the map has only ever drawn one square size. Mixed resolutions are valid under the contract
> but are **new behaviour and need a visual check**.

## Historical real-subset verification (28 Jul 2026; rerun required)

Run against `varied sample from main5.xls` (998 rows) and `reptile sample from main5.xls`
(918 rows), with the full 96,824-row species dictionary and the 155-row record-type list.

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

**The gate was also exercised against all 65 real sensitive taxa** — every `SENSITIVE = "yes"`
id from the dictionary, crossed with the seven reference shapes present in the samples
(1 m through 100 km, including a tetrad). 455 cases: **390 emitted, every one at 10 km; 65
withheld** (the 100 km case, which is undrawable). **Nothing finer than 10 km was ever
emitted.**

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
to its required resolution, the coarser of species and record type wins, and a listed type
marks the record sensitive even where it does not change the resolution. **The resolutions
themselves are not in the source — BRERC must state them.** Neither sample contains a
sensitive record type, so this path is proven by unit tests only.

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

## What BRERC must confirm before real data

1. **Per-taxon public resolutions.** The 65 ids are exactly the taxa flagged
   `SENSITIVE = "yes"` in the dictionary and match the separate sensitive-list export — that
   question is closed. But **neither file carries a resolution column**, and NBN assigns these
   individually (1/2/10/50/100 km). Also needed: the list's version and review date.
2. **The ordinary resolution.** Is 100 m publication of real locations authorised? The
   frontend accepting it is a contract fact, not a permission.
3. **A corrected classification and resolutions for all 155 record types.**
4. **Suppression threshold** (`min_records_per_cell`). 1 means no suppression: every occupied
   square is shown.
5. **Place names** — publish or withhold?
6. **Record ids** — publish BRERC's own numbers, or the derived non-reversible ids?
7. **Licence vocabulary.** `licence` is populated on 257 reptile rows and blank on all varied
   rows; its meaning is unclear, and it gates any export or download feature.
8. **Verification vocabulary.** Should `accepted_verification_values` be BRERC's exhaustive
   list? Real data contains values such as `"BRERC (1)"`, which normalise to `unknown`.
9. **Tetrads.** Withhold them, promote them to 10 km, or add tetrad support to the client
   parser? `Data_Governance_and_Compliance.md` lists 2 km as a supported public resolution,
   but the client cannot draw one.
10. **100 km references.** Same question, with no promotion available — 10 km is the coarsest
    square the client can draw.
11. **A sample containing known sensitive records**, with expected output resolutions.
12. **Where the HMAC secret lives**, how it is generated/rotated, and who holds it after
    handover.

## Still to build

The source-view preflight is now implemented in `source_contract.py`: it pins the exact
39-column `dashboard.main_data_dash` definition, validates database metadata and zero-row
cursor headers, binds the singular `sensitive` control to the 1 km rule, canonicalises
`unique_no numeric(13,2)`, and refuses incremental mode with named blockers. See
`docs/SOURCE_CONTRACT.md`.

The live-view identity workflow is also implemented: `sql/capture_main_data_dash_view.sql`
captures the exact non-pretty PostgreSQL view definition and catalogue evidence;
`scripts/prepare_view_approval.py` validates it and creates a sanitised pending hand-off; and
`scripts/verify_view_approval.py` verifies the named BRERC approval against both the contract and
raw capture. BRERC still has to run and approve it on the internal live database. See
`docs/VIEW_DEFINITION_APPROVAL.md`.

`run_pipeline` creates a candidate transformation. Synthetic tests use the explicitly named
`build_candidate_payloads`, which returns a `CandidatePreview` rather than a dictionary. The
preview is deliberately not JSON-serialisable and cannot be passed to the release builder.
Only `build_payloads(..., policy=approved_policy)` can construct a releasable dictionary: it
rechecks approval dates, review expiry, the policy decision digest and the exact approval
digest recorded by the transformation. Changing any publication rule after approval or trying
to release a development candidate fails closed. The database loader has a separate trusted
streaming path: it opens the source connector's private safe snapshot itself and accepts only
already-generalised, HMAC-keyed dispositions. Its public API does not accept caller-built rows,
dictionaries, candidate previews, connection factories or clock hooks.

Aggregation, generalisation, packaging, the trusted PostgreSQL initial-source connector and the
local ETL test/lint gates are done. The connector derives view identity, catalogue metadata,
the fixed cursor header and rows in one locked, read-only `REPEATABLE READ` transaction; see
`docs/POSTGRES_SOURCE_CONNECTOR.md`. Its synthetic-driver tests do not replace a BRERC-network
run. The ordinary complete-run pipeline still materialises its result, but the dedicated release
loader instead transforms and stages bounded safe batches before whole-candidate database
suppression and aggregation.

The connector's separate `preflight` path fetches no record rows. It can report live structural
readiness while approval is pending, but a successful preflight is not a `ValidatedSourceRun` and
cannot cross the release boundary.

Implemented but still requiring accepted integration/scale evidence: bounded safe transformation,
inactive PostgreSQL/PostGIS staging, immutable release ledgers, database reconciliation, job/event
records and atomic initial-release switching. See `docs/POSTGRES_RELEASE_LOADER.md`.

Not yet written or externally approved: the incremental source window, idempotent update/deletion
coordinator and lookup invalidation; BRERC-approved count/drop thresholds; the outbox email worker
and ETL dashboard; the frozen OpenAPI contract; read-only FastAPI and Martin services;
species/summary/provenance payload assembly; taxon-group projection; and the licensed-image
pipeline.
