# Data governance & compliance

The binding rules for anything that touches published data, locations, personal
data, images, or the public UI. These are **hard gates, not guidance**, and each
is enforced in code and covered by a test. This restates the engagement's
`Data_Governance_and_Compliance.md`; that document is the authority.

## 1. Sensitive-species locations — generalised server-side, fail-closed
UK LERCs must not publish precise locations of sensitive species (it can
facilitate wildlife crime and breaches data-supply agreements). Enforced in the
`public_occurrences` view **before any tile or API response**, using floor-to-cell
in `EPSG:27700`. Never emit precise coordinates, precise grid references, point
markers, pop-ups, or raw downloads for listed species, **badger setts**
(Protection of Badgers Act 1992), or **Schedule 1 bird nest sites** (Wildlife and
Countryside Act 1981). **Generalise, do not randomise** — present as
presence-in-a-square, never fake points. Fail closed: anything not positively
confirmed safe is generalised by default.
*Enforced by:* `db/migrations/0004_public_occurrences_view.sql`; *tested by:*
`db/tests/test_generalisation_gate.sql` and the CI `database` job. Full design in
`SENSITIVE_SPECIES.md`.

## 2. Personal data — recorder names (`Recorder1`)
Recorder names are personal data under UK GDPR. **Public tier:** omitted (the
gate does not select `recorder1`); only dataset-level attribution (`BLISS`) is
shown. **Internal tier:** full names are acceptable for staff with an operational
need, access-controlled.
*Enforced by:* the view (no `recorder1` column) + the read-only role having no
access to `occurrences`; *tested by:* gate test check (1) — forbidden columns
absent.

## 3. Species images & descriptions — licensing, fail-closed
Fetch cascade until a usable, licensed image is found: **iNaturalist** →
**GBIF** occurrence media → (description only) **Wikipedia** summary. Always
display the per-item **licence + attribution**. Only show an image whose licence
is positively recognised and in the allow-list (default commercial-safe: CC0 /
CC BY / public domain; avoid CC BY-NC if the site may become commercial). If a
reusable licence can't be confirmed, show a **named placeholder**, never a broken
or unlicensed image. Results are cached (never hot-call third parties per request).
*Enforced by:* `api/app/services/licensing.py` + `species_info.py`; *tested by:*
`api/tests/test_licensing.py`, `test_species_info.py`.

## 4. Accessibility — WCAG 2.2 AA (legal)
BRERC is part of Bristol City Council; the Public Sector Bodies Accessibility
Regulations 2018 require WCAG 2.2 AA and a published accessibility statement in the
gov.uk model format. The whole interface targets AA, with an accessible non-map
equivalent for essential map information. See `ACCESSIBILITY.md`.
*Enforced by:* the front end + `eslint-plugin-jsx-a11y`; *tested by:* `jest-axe`
tests in `web/` and the CI `frontend` job.

## 5. Security & data handling
- The provided BRERC subset is **real client data**: never commit it (`data/` is
  git-ignored), never upload it to third-party services. Only the clearly-labelled
  **synthetic** seed under `db/seed/` is versioned.
- **Read-only DB roles** for all serving queries; **parameterised SQL**; statement
  timeouts and row caps on user-facing queries. No destructive statements.
- **No secrets** in code or config; secrets live only in a git-ignored `.env`.
- Branch → pull request → review → merge; protect `main`.

## 6. In one line
Every public map/query/export passes through one tested gate that generalises
sensitive locations, strips recorder PII, enforces image licensing, and is
delivered through a WCAG 2.2 AA interface — and if any of those can't be confirmed
for a given record or component, it **fails closed**.

## Sources
NBN sensitive species <https://docs.nbnatlas.org/sensitive-species/> ·
NBN policy v6 <https://docs.nbnatlas.org/wp-content/uploads/2019/10/National-Biodiversity-Network-sensitive-species-policy_v6-002.pdf> ·
GBIF generalisation best practice <https://doi.org/10.15468/doc-5jp4-5g10> ·
`ST_SnapToGrid` <https://postgis.net/docs/ST_SnapToGrid.html> ·
Badgers Act 1992 <https://www.legislation.gov.uk/ukpga/1992/51> ·
Wildlife & Countryside Act 1981 <https://www.legislation.gov.uk/ukpga/1981/69> ·
recorder personal data <https://docs.nbnatlas.org/share-data-with-the-nbn-atlas/personal-information-in-shared-data/> ·
PSBAR 2018 <https://www.legislation.gov.uk/uksi/2018/952/regulation/9>
