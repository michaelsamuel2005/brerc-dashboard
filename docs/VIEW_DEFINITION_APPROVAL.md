# BRERC source-view identity and approval

**Implementation status:** Capture, digest, approval-envelope validation and fail-closed
release checks are implemented and tested. The live digest and BRERC approval are not yet
available because only BRERC can run the capture against its internal PostgreSQL database and
authorise the result.

**Source object:** `dashboard.main_data_dash`

**Current contract:** `brerc-main-data-dash-2026-07-31` (initial load only)

## Why three identities must remain separate

| Evidence | Current value/status | What it proves |
| --- | --- | --- |
| Received PDF SHA-256 | `567f614773df83609c3dd1a63f6b5d44fd98406d67ef60f2e5eb66f1fcebb72d` | The exact client document reviewed by the team has not changed. |
| Live view-definition SHA-256 | Pending BRERC capture | The exact UTF-8 result returned by PostgreSQL for `pg_get_viewdef(view_oid, false)`. |
| BRERC view-identity approval | Pending named BRERC owner | BRERC has authorised that captured SQL, ordered columns, owner, options and PostgreSQL version as a source version for this dashboard. |

The PDF contains a complete `CREATE OR REPLACE VIEW` statement, but its checksum is not a
live-database checksum. PostgreSQL reconstructs the underlying `SELECT`; it does not return the
original `CREATE VIEW` text. The non-pretty OID form is used because PostgreSQL documents it as
the more stable representation for dump-style use. See the official
[system-information function documentation](https://www.postgresql.org/docs/current/functions-info.html).

The repository therefore pins the PDF checksum as provenance, but it does not pretend that the
PDF proves what is running in BRERC's database today.

## Responsibility and authority

- The project team supplies and tests the capture and verification tools.
- Shankar coordinates the request and evidence route with BRERC.
- A BRERC database operator runs the catalogue-only capture inside BRERC's network.
- An authorised BRERC data owner reviews the capture and grants or refuses approval.
- The production connector repeats the comparison during each extraction.

The JSON envelope records a claimed procedural approval; it is not a digital signature and cannot
authenticate a person by itself. Shankar must verify the sender and authority through the agreed
BRERC channel, and BRERC must retain the referenced decision evidence. The source contract also
requires the independently confirmed environment and the exact organisation `BRERC`; a file that
claims a local environment or another organisation cannot release data.

## One-time BRERC capture

This step must be run by BRERC, or by Shankar while operating under BRERC's approved access,
against the database that hosts the real view. A development database is not a substitute.

Use BRERC's protected connection service or equivalent. Do not put a password in the command,
shell history, YAML, email or Git.

```bash
cd api
umask 077
mkdir -p /a/brerc-controlled/location/view-attestation

PGSERVICE=brerc-internal \
psql -X -qAt --set=ON_ERROR_STOP=1 \
  --file=sql/capture_main_data_dash_view.sql \
  > /a/brerc-controlled/location/view-attestation/main-data-dash.brerc-view-capture.json
```

`PGSERVICE=brerc-internal` is an example name, not a repository setting. BRERC should use its
normal protected connection method. `-X` prevents local `psqlrc` customisation from changing the
session. The SQL starts a `READ ONLY, REPEATABLE READ` transaction, applies a five-second lock
timeout and acquires `ACCESS SHARE` on the exact view before reading catalogue metadata. It does
not read wildlife record rows. PostgreSQL documents that successive reads in this isolation level
use one stable snapshot; see
[transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html).
The explicit relation lock additionally prevents concurrent replacement, alteration, ownership
change or drop from mixing two view identities during capture. It is the weakest table lock and
does not block ordinary data access; if a migration already holds a conflicting lock, capture
fails after the timeout rather than waiting indefinitely.

The lock and its timeout strengthen how evidence is acquired; they do not change the definition
hash algorithm or normalise the captured SQL. The digest remains the SHA-256 of the exact UTF-8
bytes returned by `pg_get_viewdef(view_oid, false)` under the fixed rendering settings.

The capture deliberately includes internal view SQL, database and role names, and the relation
OID. Keep it outside this repository and transmit it only through the project-approved secure
route. The `.gitignore` patterns are a second line of defence, not permission to move it into the
repository.

## Validate and prepare the approval hand-off

On a trusted machine containing this exact repository revision:

```bash
cd api
python scripts/prepare_view_approval.py \
  /a/brerc-controlled/location/view-attestation/main-data-dash.brerc-view-capture.json \
  --output /a/brerc-controlled/location/view-attestation/main-data-dash.brerc-view-approval.pending.json
```

The command fails if the object is not the exact permanent ordinary view, if its 39 ordered
columns or types differ, if the raw text and UTF-8 bytes disagree, or if any capture field is
missing. Its output contains hashes and approval blanks, but removes the raw SQL, database name,
capture role and OID. It never grants approval.

The capture uses fixed PostgreSQL session settings for string, date, interval, time-zone, numeric
and byte rendering. A session-setting mismatch is rejected rather than allowed to produce an
ambiguous digest.

## BRERC approval fields

A BRERC data owner must review the raw captured SQL and complete the pending JSON with:

- `status`: change to `approved` only after review;
- `sourceVersion`: BRERC's immutable name for this view version;
- `sourceEnvironment`: the BRERC environment captured, for example the production source;
- `approvedBy`: the named BRERC approver;
- `approverRole`: that person's BRERC role;
- `approverOrganisation`: the approver's organisation;
- `approvedOn`: ISO date, `YYYY-MM-DD`;
- `reviewExpiresOn`: an ISO date if BRERC uses review expiry, otherwise `null`;
- `evidenceReference`: the retained email, ticket or decision-record reference.

The approval should say:

> I confirm that this captured definition and ordered schema are the authoritative BRERC source
> view for the dashboard, and that the recorded hashes identify the version approved for the
> stated load mode.

The project team must not fill these fields on BRERC's behalf. The completed evidence should be
returned through Shankar, who is the project's client-contact route.

The pending file still contains the PostgreSQL view-owner role. Treat it as controlled project
evidence until BRERC confirms whether that role name and the eventual approver details may be
stored in this repository.

## Verify the returned approval

Verify both the completed envelope and the original raw capture:

```bash
cd api
python scripts/verify_view_approval.py \
  /a/brerc-controlled/location/view-attestation/main-data-dash.brerc-view-approval.json \
  --expected-source-environment 'THE EXACT ENVIRONMENT NAME CONFIRMED BY BRERC' \
  --capture /a/brerc-controlled/location/view-attestation/main-data-dash.brerc-view-capture.json
```

The expected environment must come independently from BRERC's retained decision; do not simply
copy an unverified value out of the approval JSON. The command must print `OK`. Without
`--capture`, it validates the envelope and repository
contract but explicitly warns that live equality was not checked.

The verifier checks three separate hashes:

- the **definition hash** covers the exact `pg_get_viewdef(oid, false)` UTF-8 bytes;
- the **catalogue-column hash** covers every captured ordered metadata field, including UDT,
  nullability and collation evidence, while the contract separately checks the 39 public source
  names and types;
- the **capture-evidence hash** binds the exact approval event, including its timestamp and raw
  catalogue context, without reproducing those internal values in the pending envelope.

The composite **view-identity hash** binds the schema/name, relation kind, exact PostgreSQL server
version, owner, sorted view options, definition hash, reviewed contract-column hash and full
catalogue-column hash. These hashes detect change; they do not authenticate the approver or attest
the current data rows.

After verification, a maintainer opens a reviewed pull request that adds the approved identity to
a new source-contract version. Do not commit the raw capture or original PDF. Before committing a
completed approval envelope, BRERC must also confirm that the approver's name, role and evidence
reference may be stored in this repository; otherwise retain that file in controlled evidence and
commit only the approved non-reversible identity fields and decision reference.

## What happens at runtime

The production PostgreSQL connector repeats the same catalogue capture in the same read-only,
repeatable-read transaction used to obtain the column metadata, query header and source rows. It
takes `ACCESS SHARE` before identity capture and holds it through extraction, computes the digest
internally, and rolls back the source transaction on success or failure. Callers cannot supply a
checksum and claim it was observed. See
[`POSTGRES_SOURCE_CONNECTOR.md`](POSTGRES_SOURCE_CONNECTOR.md).

Any SQL, column, owner, view-option or PostgreSQL-version mismatch stops the job before a record is
processed. The previous public release remains active. A view-definition digest identifies the
source logic; it does not attest current row contents or replace reconciliation and count-drop
checks.

## Exact remaining client action

This item becomes **BRERC-approved** only when all three events have occurred:

1. BRERC runs the supplied capture against the live internal view.
2. A named authorised BRERC data owner reviews and approves that exact capture and assigns a
   source version.
3. The team verifies the returned envelope against the raw capture and integrates it through a
   reviewed source-contract change.

Until then the code intentionally reports `BLOCKED_SOURCE_RELEASE`. This is a safety result, not a
failed implementation.

Even after view approval, the current 39-column contract supports initial loading only.
`date_mdb_modified` is absent, so incremental loading remains a separate blocked contract change.

## Completion checklist

- [x] Received PDF checksum and provenance recorded.
- [x] Exact PostgreSQL capture profile and fixed session settings implemented.
- [x] Definition, contract-column, complete catalogue-column, capture-evidence and composite
  identity hashes implemented.
- [x] Sanitised pending-template and strict approval verifier implemented.
- [x] Release remains fail-closed when approval, source environment or runtime evidence is absent.
- [ ] BRERC runs the capture against its internal live view.
- [ ] An authorised BRERC owner assigns the version and approves the exact capture.
- [ ] Shankar confirms the authority and evidence route; verification passes with the raw capture.
- [ ] A reviewed source-contract change binds the approval.
- [x] The production connector repeats the identity check inside each locked extraction snapshot
  (unit-tested with a synthetic driver; BRERC execution remains pending).
