# BRERC source-view contract

**Status:** Initial-load source contract, trusted connector and atomic destination-loader
mechanisms implemented. Public release and incremental loading remain blocked pending BRERC
source/decision evidence, accepted PostGIS lifecycle evidence and representative scale testing.

**Contract version:** `brerc-main-data-dash-2026-07-31`

**Source:** Client-supplied definition of the PostgreSQL view
`dashboard.main_data_dash`, dated 31 July 2026.

## What is now enforced

Before a live database path may process a record, it must prove all of the following:

1. The source is the `dashboard.main_data_dash` **view**, not an arbitrary table.
2. Its complete `information_schema.columns` metadata exactly matches the 39 confirmed
   columns, in order, including varchar lengths and numeric precision/scale.
3. The query uses an explicit, reviewed projection. `SELECT *` is not accepted.
4. The cursor/result header exactly matches that projection, including for a zero-row batch.
5. `unique_no` maps to the private source identity and is canonicalised as `numeric(13,2)`
   before duplicate detection or HMAC generation.
6. `sensitive` maps exactly to the row-level safety control.
7. Only `No` takes the ordinary-location path. `Yes`, null, blank, whitespace and unknown
   values fail closed as sensitive.
8. A row marked sensitive is shown at exactly a 1 km floor; any coarser taxon or record-type
   rule still wins.
9. Configured record-type sensitivity rules require the exact `record_type` mapping and column;
   the rules cannot remain silently dormant, even for an empty result.
10. A releasable payload requires a named, dated, unexpired approval bound to the exact
    publication decisions used for that transformation. Development candidates cannot cross
    this release boundary.
11. Individual record rows are disabled unless BRERC explicitly approves them. Aggregated
    species-by-year grid cells can still be published without exposing row-level records.
12. Map suppression is applied at species + year + cell + precision, so unrelated species or
    years can never be combined merely to pass a minimum-count threshold.
13. Development payloads are wrapped in a non-serialisable `CandidatePreview`. The release loader
    obtains safe HMAC-keyed dispositions only through the trusted connector's private locked
    snapshot path; callers cannot provide rows, metadata, headers, connection factories or clock
    hooks to the public coordinator API.

The public output remains constructed from an allow-list. Raw `easting`, `northing`,
`comments`, `bliss`, `place`, `precise_date`, `unique_no` and `sensitive` values do not gain
public fields merely because they exist in the source view.

The HMAC secret used to replace `unique_no` is not a source-code setting: production requires
at least 32 bytes of cryptographically random secret material supplied externally. It is
excluded from object representations and reports. Public identifiers use 128 bits of the
HMAC, while duplicate detection remains mandatory.

Raw `source` text is not copied. If a public source label is approved, the ETL emits the
controlled value `BRERC`; this prevents names, addresses or internal references embedded in a
free-text source field from reaching the public tier.

## What the schema check does not prove

The 39-column contract check proves names, order and PostgreSQL types. It cannot prove that
the live view still selects, joins and calculates those columns with the reviewed meaning.
The client-supplied PDF contains the complete `CREATE OR REPLACE VIEW` statement. The repository
pins that received document's SHA-256 as provenance, but does not treat it as live database
evidence: PostgreSQL's reconstructed `pg_get_viewdef` output is not byte-identical to the pictured
DDL. BRERC has not yet supplied an authoritative live version identifier or approved live-view
identity. The initial-load preflight therefore emits an explicit warning, and the release boundary
refuses to build releasable payloads under this contract version.

The deterministic capture SQL, exact-byte hashing profile, sanitised approval template and
approval verifier are implemented. A valid approval is a full envelope: source version and
independently pinned environment, exact definition and composite identity hashes, PostgreSQL
version, view owner/options, reviewed and complete catalogue-column digests, capture-evidence
digest and time, named BRERC approver, BRERC organisation and role, approval date and retained
evidence reference.
A bare 64-character hash cannot make this contract release-ready. The operator procedure is in
[`VIEW_DEFINITION_APPROVAL.md`](VIEW_DEFINITION_APPROVAL.md).

Before production extraction, BRERC must run that capture against its internal live view and
approve the result. The connector must compare that identity and must also record safe structural
checks such as row count and the observed `sensitive` vocabulary. A matching 39-column header
alone is not production sign-off.

The lower-level Python entry point accepts metadata, headers and rows as arguments so it can be
tested without BRERC's network. Those values are not independent trust evidence. The trusted
PostgreSQL connector obtains the view definition, `information_schema` metadata, fixed-query
cursor header and rows itself using one connection and one read-only `REPEATABLE READ`
transaction. It takes `ACCESS SHARE` on the exact view before inspecting catalogue identity,
closing the race with a concurrent view replacement or alteration. Application callers cannot
submit their own digest, header, metadata or rows to that connector. The complete operational
contract is in [`POSTGRES_SOURCE_CONNECTOR.md`](POSTGRES_SOURCE_CONNECTOR.md).

Its non-data `preflight` operation is intentionally usable while release approval is pending. It
validates the locked live identity, full schema and fixed cursor header without fetching a row and
returns `release_ready=False` for this current contract. That is readiness evidence only—not a
BRERC approval, an extracted candidate or permission to publish.

Before activation, the loader checks the complete initial source count against configured bounds
and rejects an empty public candidate. The database then independently reconciles the safe ledger,
suppression cohorts, aggregates, geometry, optional rows and manifest. BRERC must approve the
initial and future replacement/drop bounds; they must not be guessed from the small development
samples. A failure leaves the old public release active.

## Confirmed schema

| # | Column | PostgreSQL type |
|---:|---|---|
| 1 | `scientific_name` | `character varying(120)` |
| 2 | `common_name` | `character varying(120)` |
| 3 | `grid_ref` | `character varying(25)` |
| 4 | `place` | `character varying(254)` |
| 5 | `date_of_record` | `character varying(50)` |
| 6 | `abundance` | `character varying(35)` |
| 7 | `sex_stage` | `character varying(45)` |
| 8 | `record_type` | `character varying(55)` |
| 9 | `start_date` | `date` |
| 10 | `species_no` | `character varying(20)` |
| 11 | `precise_date` | `date` |
| 12 | `vague_date` | `character varying(35)` |
| 13 | `vitality` | `character varying(15)` |
| 14 | `digital_or_paper` | `character varying(10)` |
| 15 | `date_entered` | `date` |
| 16 | `bnes` | `character varying(4)` |
| 17 | `bcc` | `character varying(3)` |
| 18 | `sglos` | `character varying(4)` |
| 19 | `nsom` | `character varying(4)` |
| 20 | `year_end` | `character varying(5)` |
| 21 | `year_start` | `character varying(5)` |
| 22 | `end_date` | `date` |
| 23 | `comments` | `character varying(254)` |
| 24 | `source` | `character varying(50)` |
| 25 | `bliss` | `character varying(100)` |
| 26 | `taxa_brerc` | `character varying(60)` |
| 27 | `unique_no` | `numeric(13,2)` |
| 28 | `licence` | `character varying(1)` |
| 29 | `sensitive` | `character varying(4)` |
| 30 | `taxo_id` | `character varying(20)` |
| 31 | `easting` | `numeric(13,2)` |
| 32 | `northing` | `numeric(13,2)` |
| 33 | `taxa_nb` | `text` |
| 34 | `brerc_status` | `text` |
| 35 | `national_status` | `text` |
| 36 | `legal_protection` | `text` |
| 37 | `bap` | `text` |
| 38 | `rspb` | `text` |
| 39 | `brerc_notable` | `text` |

The view SQL uses an inner join to `lookups.distinct_species` on scientific name. Lookup
changes can therefore change, add or remove view output even when the underlying record's
own modification date does not change.

## Incremental loading is deliberately unavailable

`date_mdb_modified` was mentioned in later correspondence, but it is absent from the
confirmed 39-column definition. Adding it to the live view is schema drift against this
version and requires a new reviewed contract rather than silently changing this one.

The incremental mode currently exits before row extraction with all blockers listed:

- Updated view DDL containing `date_mdb_modified` has not been received.
- Its type, nullability, same-day behaviour and guarantee on every modification are not
  confirmed in a versioned schema.
- `unique_no` is not yet confirmed non-null, unique, stable and never reused.
- Deletions, withdrawals and source-key changes have no confirmed signal.
- Lookup-table changes may bypass the main-data modification marker.
- The incremental coordinator does not yet build a complete replacement candidate from an
  approved change window and deletion signal.
- Inclusive-watermark, affected-aggregate and deletion semantics have not been approved or
  validated against a revised live BRERC view.

There is no force flag. `date_entered` is not a substitute.

When BRERC supplies the missing guarantees, create a new contract version. If the marker is
a PostgreSQL `date`, the eventual query must use an inclusive overlap (`>=` the last
successful date), idempotent upserts, and advance the watermark only in the same successful
release operation that activates the validated candidate.

Before incremental mode is enabled, one immutable release manifest must also bind the actual
load mode, source snapshot/as-of time, watermark window, observed view digest, fixed
projection/query version, source and candidate counts/digests, and policy, contract and ETL
versions. The successful watermark update and public-release activation must commit in the
same database transaction; a failed job advances neither.

## Configuration boundary

The database adapter reads connection **environment-variable names**, source
object names and source mappings from `configuration.yaml`. Passwords, DSNs and real values
must remain outside the repository. `api/configuration.example.yaml` now provides the
reviewed, credential-free template, including all 39 columns and an explicit minimal
projection. Configuration is deployment input, not source approval.

Configuration may select where the source lives, but it must not be able to disable:

- the versioned schema check;
- the `sensitive` mapping or 1 km row-level rule;
- the private-field/public-field allow-list;
- reconciliation or atomic release gates.

Those are reviewed safety controls, not deployment switches.

## Scope limitation

This implementation validates the confirmed BRERC view contract and canonicalises its source key.
The dedicated loader path transforms bounded batches inside one locked source snapshot and writes
only already-safe dispositions to inactive PostgreSQL/PostGIS staging. Whole-candidate suppression,
aggregation, database reconciliation and one atomic initial-release switch are implemented. The
ordinary `extract_initial()` convenience API still materialises a complete validated run; the
loader does not use that API for its large-load path.

It does **not** yet perform an approved incremental window, deletion reconciliation, failure-email
delivery, ETL-dashboard monitoring, FastAPI serving or Martin vector tiles. Initial operation at
BRERC's roughly five-million-row scale still requires accepted runtime, lock-duration, memory and
peak-disk evidence. Connector operation is documented in
[`POSTGRES_SOURCE_CONNECTOR.md`](POSTGRES_SOURCE_CONNECTOR.md); destination operation and remaining
blockers are documented in [`POSTGRES_RELEASE_LOADER.md`](POSTGRES_RELEASE_LOADER.md).
