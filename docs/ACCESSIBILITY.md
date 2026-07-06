# Accessibility (WCAG 2.2 AA)

WCAG 2.2 AA is a **legal requirement** for this dashboard: BRERC is part of Bristol
City Council, a public sector body under the Public Sector Bodies (Websites and
Mobile Applications) (No. 2) Accessibility Regulations 2018. This page is how we
meet it and how we keep meeting it.

## The map exemption — and why it doesn't let us off

Regulation 4(2)(d) exempts **online maps** from the regulations. But the essential
information a map conveys must still be available accessibly, and the surrounding
dashboard (controls, panels, search) is fully in scope. So:

- The interactive WebGL map is the exempt part.
- **Everything around it targets AA**, and the map's essential information — which
  species are recorded where, and how many — is also provided as a **filterable
  data table** (`web/src/components/DataTable.tsx`) that renders the exact same
  generalised, counted cells the map draws.

## What we do

- **Semantics & structure:** one `<h1>`, landmark regions (`header`, `main`,
  `aside`), a **skip link** to the map/records, explicit `lang="en-GB"`, and a
  `<title>` that matches the embedding `<iframe title>` (2.4.2 / 4.1.2).
- **Keyboard:** everything operable by keyboard; visible focus with a thick,
  high-contrast outline (2.4.7 / 2.4.11); the accessible table means no essential
  task depends on a mouse over the map.
- **Contrast & colour:** text ≥ 4.5:1; **nothing is conveyed by colour alone**
  (1.4.1) — the legend uses text and circle **size**, and sensitive cells carry a
  text **badge** in the table and a distinct stroke on the map.
- **Names/roles:** `react-aria-components` provides correct combobox ARIA and
  keyboard interaction rather than hand-rolled ARIA.
- **Motion:** honours `prefers-reduced-motion`.
- **Images:** species photos have meaningful `alt`; the licence/attribution is
  shown; a named placeholder is used when no reusable image exists.

## How we test (continuously, not once)

- **Automated, in CI:** `eslint-plugin-jsx-a11y` (lint) and **`jest-axe`** (axe
  runs against the DOM components) in `web/`, on every push/PR.
- **Manual, before each milestone:** a keyboard-only pass, and at least one
  screen-reader pass (NVDA or VoiceOver) before the mid-project review.
- **Recommended:** a professional audit if BRERC can fund one, and Lighthouse
  spot-checks on the built app.

Automated tools catch a minority of issues; the manual passes are where AA is
really won. Keep the data table in step with whatever the map shows.

## Publish and maintain the statement

The regulations require a published **accessibility statement** in the gov.uk
model format, kept under review. A ready-to-complete template is in
`ACCESSIBILITY_STATEMENT.md` — BRERC fills in the compliance status, known issues,
contact route, and dates before launch.

## Sources
<https://www.gov.uk/guidance/accessibility-requirements-for-public-sector-websites-and-apps> ·
<https://www.legislation.gov.uk/uksi/2018/952/regulation/4> ·
<https://www.legislation.gov.uk/uksi/2018/952/regulation/9> ·
<https://www.gov.uk/guidance/model-accessibility-statement> ·
WCAG 2.2 <https://www.w3.org/TR/WCAG22/>
