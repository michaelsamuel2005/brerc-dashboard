# BRERC public dashboard — publication decisions and sign-off record

**Document version:** 0.1
**Prepared:** 11 August 2026
**Status:** Decision request — **not approved for public release**
**Scope:** Public species distributions, aggregate statistics and any future occurrence rows

## Purpose

This record separates three things that must not be confused:

- **Confirmed evidence** — facts supported by the supplied view definition, controlled lists
  or the implemented safety boundary.
- **Proposed safe interim** — a conservative engineering setting. It is not permission to
  publish.
- **BRERC approval required** — the decision that the authorised BRERC data owner must record
  before a production release can be activated.

The prototype, a test fixture and the fact that the software can render a value are not
publication approval. Blank sign-off fields mean **not approved**.

## Recommended initial-release position

Subject to BRERC approving the underlying data licence, the recommended first release is:

1. aggregate distribution cells and aggregate year/species statistics only;
2. ordinary public distribution at 1 km, never finer than the source record;
3. the source `sensitive` rule and any approved coarser taxon or record-type rule applied
   before aggregation;
4. sparse cells suppressed consistently from every public view;
5. no individual occurrence rows, exact record types, abundance, place names, comments,
   precise dates, source identifiers or coordinates;
6. no photograph unless its rights and attribution have been documented per asset; and
7. no verification counts or occurrence-level verification verdicts while the confirmed source
   view has no verdict field; and
8. no download or redistribution feature until that use is separately licensed.

This position remains blocked from public activation until the sign-off table is completed.

## 1. Location precision

### Confirmed evidence

- The supplied source view contains `grid_ref`, precise `easting` and `northing`, and a
  row-level `sensitive` field. Precise coordinates are private inputs and are not public
  output fields.
- The confirmed view rule states that a row marked sensitive has a **1 km minimum**. Only an
  explicit `No` follows the non-sensitive route; blank, null or unfamiliar values fail closed.
- Taxon, row-level and record-type protections are independent. Where several apply, the
  **coarsest** required result must win.
- The current browser contract can draw 100 m, 1 km and 10 km grid squares. That is a technical
  capability, not permission to publish at those resolutions.
- The current client cannot draw 2 km tetrads or letters-only 100 km references. The pipeline
  can recognise them as inputs but must not emit a shape the client cannot represent honestly.

### Proposed safe interim

| Case | Proposed treatment before BRERC approval |
|---|---|
| Ordinary public distribution | 1 km minimum |
| Source row `sensitive = Yes` | 1 km minimum; any approved coarser rule still wins |
| Null, blank or unknown `sensitive` value | Treat as sensitive, never as ordinary |
| Taxon or record type known to need protection but with no approved resolution | Withhold |
| Unknown or unresolved taxon | Withhold |
| Source record already coarser than the policy | Keep the source resolution; never sharpen |
| 2 km or 100 km input that the client cannot draw | Withhold; do not silently re-label it |

The proposed 1 km ordinary value replaces the prototype's possible 100 m output for the
initial aggregate release. It does not authorise public occurrence rows at 1 km.

### BRERC approval required

BRERC must confirm:

- the ordinary minimum public resolution;
- whether 1 km is sufficient for every source row marked sensitive;
- a versioned per-taxon schedule where a taxon requires more than the row-level rule;
- the resolution for every sensitive record type;
- the treatment of tetrads and 100 km references; and
- the owner and review date of each sensitivity schedule.

## 2. Record-data licence

### Confirmed evidence

- The view includes a one-character `licence` field, but no authoritative codebook or public
  reuse statement has been supplied.
- A code being present does not establish that public display, download and onward reuse are
  all permitted. Those are separate uses.
- The safety boundary can apply an exact allow-list and withhold blank or unrecognised codes.
  It must not guess what a code means.
- The current implementation makes one composite record-licence decision before producing any
  public payload. A permitted record can therefore contribute to public JSON/API responses, the
  map, accessible table, year series and totals. It does not currently support different licence
  choices for different public surfaces.
- There is no public download feature in the current implementation.

### Proposed safe interim

- Keep the production licence allow-list empty and block public activation until BRERC supplies
  the codebook and authorisation.
- Once approved, admit only exact codes that BRERC identifies as permitting the intended public
  display.
- Keep CSV, API bulk export and other download/redistribution features disabled. Enable them
  only under a separate, explicit reuse decision.
- Show the approved public attribution and terms link supplied by BRERC; never copy uncontrolled
  free text from the source `source` field.
- Treat licence enforcement as not applicable only if BRERC explicitly signs that decision.
  Absence of a codebook or a blank policy field is not evidence that licensing is irrelevant.

### BRERC approval required

BRERC must provide the meaning of every possible `licence` code and state, for each allowed
code, whether it permits:

1. on-screen aggregate display;
2. on-screen occurrence-row display;
3. machine-readable API access;
4. download and onward reuse; and
5. any required attribution or terms link.

If BRERC requires map-only display, table-only display or any other per-surface distinction, that
cannot be represented by the current composite gate. It requires a code change, new contract
fields and tests before approval can be implemented faithfully.

## 3. Photograph and image licence

### Confirmed evidence

- The supplied occurrence and species files do not constitute an approved image library.
- A species name or web URL is not evidence that an image may be copied or modified.
- Image rights are independent of the record-data licence.

### Proposed safe interim

- Use the existing neutral **“Photograph pending licence”** fallback.
- Publish an image only when its asset record contains: source URL or retained source reference,
  copyright holder/creator, licence name and version, required attribution, permitted use, and
  date checked.
- Do not scrape images or infer a licence. If the evidence is incomplete, the fallback remains.
- Store the image attribution separately from the species description so it can be displayed
  and audited without changing descriptive text.
- Keep every image fallback-only until a backend asset registry validates the asset reference,
  retained rights evidence, review/expiry status and takedown status. Missing, expired, disabled
  or withdrawn entries must resolve to the fallback rather than an image URL.

### BRERC approval required

BRERC must either supply approved assets and metadata, or approve a named external image source,
the licences that may be accepted, the attribution format and whether cropping/resizing is
permitted. Approval does not bypass the backend registry or its expiry and takedown checks.

## 4. Species-description provenance and licence

### Confirmed evidence

- The supplied source view and species files do not provide an approved, versioned source for
  the descriptive prose shown in the prototype.
- A factual species name does not grant permission to copy a third party's descriptive text.
- Description provenance and image provenance are separate decisions and must not be combined
  into one generic content credit.

### Proposed safe interim

- Omit the species description unless its exact text, source, reuse basis and BRERC approval are
  all present in a controlled backend content record.
- Keep source/credit in a dedicated `descriptionSource` field rather than appending it to the
  description sentence.
- For approved text, retain the source reference, author or rights holder where applicable,
  licence or written permission, required attribution, text version, approval date and review
  date. An expired, withdrawn or incomplete record must produce no description.

### BRERC approval required

BRERC must approve either the exact descriptions or an authorised source and editorial process.
It must also confirm the reuse basis, attribution wording, responsible reviewer and review cycle.
Until then, the public species page must omit descriptive prose rather than present unverified or
unlicensed text.

## 5. Sparse-cell suppression

### Confirmed evidence

- A threshold of 1 means no suppression: every occupied cell can appear.
- The implemented boundary can apply a minimum count at the cohort
  **species × year × grid cell × published precision**.
- Suppressing a map cell while leaving the same records in a table, chart or total does not
  protect the information. Suppression must be consistent across all public outputs.

### Proposed safe interim

- Keep the production suppression threshold **unset** and block public activation until BRERC
  approves an exact value.
- Once approved, apply suppression after safety generalisation and before building the public
  map, accessible cell table, year series and totals.
- Remove suppressed cohorts consistently; do not present them as zero.
- Do not release a total or filter combination from which a suppressed value can be recovered
  by subtraction.

No numerical threshold is inferred from the prototype, sample size or implementation default.
Public activation remains blocked until BRERC chooses the threshold and confirms whether any
taxon or record-type class needs a stronger rule.

### BRERC approval required

BRERC must confirm the default threshold, any class-specific thresholds, whether suppression is
required across all years as well as individual years, and the public wording used when data are
withheld.

## 6. Record-type safety and public display

### Confirmed evidence

The supplied `drop down lists (1).xls` contains **155 nonblank, unique** `Recordtype` values.
The current evidence does **not** support the previously repeated higher figure:

- **47 of 155** record types have an aligned `sensitive = yes` value on the same row.
- Cell `M234` contains `yes`, but the corresponding `Recordtype` cell `C234` is blank. This is
  an orphan flag and cannot be assigned safely.
- Cell `C308` contains `raptor or owl nest (sensitive record)`, but its corresponding sensitivity
  cell `M308` is blank.
- Matching text that merely contains “sensitive record” is unsafe because the controlled list
  also contains labels that explicitly say “not sensitive record”.

The two supplied occurrence samples contain no positive sensitive-record-type example, so they
cannot validate this path against a real occurrence. No row-level occurrence values are included
in this document.

The software already keeps two decisions separate:

1. use raw `record_type` internally to protect locations; and
2. decide independently whether the exact label may be displayed publicly.

### Proposed safe interim

- Never infer safety from words inside the label.
- Do not treat the 47-row extraction as an approved production list.
- Before release, require a corrected, versioned 155-value list in which every value has an
  explicit ordinary/sensitive classification and every sensitive value has an approved public
  resolution.
- Withhold an unknown, blank or newly introduced record type until that complete vocabulary is
  approved or BRERC confirms another fail-closed treatment.
- Continue using approved record-type rules internally even when the label is not public.
- Set public record-type display to **off** for the initial release.

### BRERC approval required

BRERC must:

- resolve `C234/M234` and `C308/M308`;
- confirm whether the live view's row-level `sensitive` value already incorporates record-type
  sensitivity;
- approve the complete record-type classification and required resolution for each sensitive
  type;
- name the list owner and review date; and
- decide separately whether exact record-type labels may ever appear in public occurrence rows.

## 7. Individual occurrence rows

### Confirmed evidence

- Aggregate grid cells and their accessible table can be published without publishing individual
  occurrence rows.
- Row-level publication creates additional inference and licensing risk even after coordinates
  have been removed.
- The safety boundary supports a separate switch for occurrence rows and separate switches for
  higher-risk fields such as abundance and record type. These are off unless explicitly approved.

### Proposed safe interim

- Set individual occurrence rows to **off** for the initial release.
- Publish the accessible aggregate grid-cell table as the map's non-visual equivalent.
- Do not expose original record identifiers, coordinates, precise dates, place, comments, raw
  source text, sensitivity markers, abundance or exact record type.
- If BRERC later wants occurrence rows, treat that as a new policy version and approve the exact
  fields, precision, licence, pagination, identifier scheme and retention behaviour before
  implementation.

### BRERC approval required

BRERC must choose either aggregate-only publication or occurrence-row publication. If it chooses
rows, it must approve an exact field allow-list and state whether abundance and record type are
allowed. Approval of the map does not imply approval of rows.

## 8. Verification publication

### Confirmed evidence

- The confirmed live `dashboard.main_data_dash` view has no record-verification verdict field.
  Verification is therefore **unavailable**, not zero and not “unverified”.
- The current production candidate must omit aggregate `verifiedCount` values and per-occurrence
  `verified` verdicts, and must advertise verification as unavailable to the browser.
- Aggregate verification counts and verdicts on individual occurrence rows are separate public
  disclosures. Approval of aggregate counts does not approve row verdicts.

### Proposed safe interim

- Set aggregate verification publication to **unavailable** and publish no verification counts.
- Set per-occurrence verification publication to **off**, including if occurrence rows are later
  enabled for another reason.
- If a future source view adds a verdict field, continue withholding it under the existing policy.
  A new policy may publish aggregate counts only after BRERC approves the exact, complete source
  vocabulary that counts as accepted. Publishing each row's verdict requires a second, separate
  approval and must never be inferred from the aggregate decision.

### BRERC approval required

Before any verification data is published, BRERC must separately approve:

1. whether aggregate verified counts may be shown;
2. the exact accepted-verdict vocabulary and treatment of every blank, unknown or new value; and
3. whether verdicts may also appear on individual occurrence rows, if those rows are approved.

The approval evidence must identify the source verdict column and controlled-list version. A
future column appearing in the view is not itself permission to expose it.

## 9. Release control

- The approved values must be represented in one versioned publication policy.
- The policy must record a named BRERC approver, approval date, review date and evidence
  reference.
- Approval must be bound to the exact decision set. Changing precision, record or content
  licences, image/description provenance, suppression, record-type rules or row-level fields
  creates a new policy and requires renewed approval.
- An approval envelope or digest proves that the recorded fields have not changed; it does not
  authenticate the named person or prove that they have authority to approve publication.
- Shankar, as the project advisor and client-contact route, must verify through a trusted channel
  that the named approver is an authorised BRERC decision owner and that the cited evidence is
  genuine and retained. That verification and its reference must be recorded before activation.
- A failed, incomplete, expired or blank approval must leave the currently active public release
  unchanged.

## Sign-off table

Complete every applicable row. Entering an approver on one row does not approve any other row.
Blank cells mean **not approved**.

| ID | Decision | Proposed safe interim | BRERC-approved value / decision | Approver name and role | Approval date | Evidence / retained reference |
|---|---|---|---|---|---|---|
| P-01 | Ordinary minimum public precision | 1 km |  |  |  |  |
| P-02 | Row marked sensitive | 1 km minimum; coarser rule wins |  |  |  |  |
| P-03 | Per-taxon sensitive resolutions | Withhold where the required resolution is unapproved |  |  |  |  |
| P-04 | Tetrad and 100 km inputs | Withhold |  |  |  |  |
| L-01 | Record-data licence mode and codes for all current public surfaces | Empty composite allow-list; no public activation |  |  |  |  |
| L-02 | Download/redistribution feature | Not implemented; disabled |  |  |  |  |
| I-01 | Image sources and accepted licences | Fallback only |  |  |  |  |
| D-01 | Species-description source, licence and approval | Omit description until all are supplied |  |  |  |  |
| S-01 | Minimum records per species/year/cell/precision cohort | Unset; public activation blocked |  |  |  |  |
| S-02 | Additional or class-specific suppression | None assumed; release blocked pending decision |  |  |  |  |
| R-01 | Corrected 155-value record-type classification | Required before release |  |  |  |  |
| R-02 | Sensitive record-type resolutions | Withhold until approved |  |  |  |  |
| R-03 | Public display of exact record type | Off |  |  |  |  |
| O-01 | Individual occurrence rows | Off; aggregates only |  |  |  |  |
| O-02 | Abundance and other optional row fields | Off |  |  |  |  |
| V-01 | Verification publication: aggregate counts, exact accepted vocabulary and separate per-row verdict decision | Unavailable; hide aggregate counts and per-row verdicts |  |  |  |  |

## Overall release authorisation

This final declaration is completed only after all blocking rows above have been resolved.

| Field | Entry |
|---|---|
| Publication policy version |  |
| Authorised for public release |  |
| BRERC approver name |  |
| BRERC approver role |  |
| Approval date |  |
| Review due date |  |
| Retained approval/evidence reference |  |
| Named BRERC authority verified by Shankar |  |
| Trusted-channel verification date/reference |  |
| Notes or conditions |  |
