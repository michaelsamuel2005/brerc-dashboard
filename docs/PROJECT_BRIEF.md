# BRERC Public Dashboard — Project Brief for the Project Advisor

**Engagement:** 180 Degrees Consulting (Bristol) × Bristol Regional Environmental Records Centre (BRERC)<br>
**Prepared by:** Michael Samuel (Front-End Workstream, WS1) · **Date:** 9 July 2026<br>
**Client contact:** Tim Corner (BRERC Manager) · **180DC reviewer:** Jaslyn Leong (Head of Data Science)

**Purpose:** to present the project and proposed plan for the advisor to *validate and verify* — showing Michael's work alongside the team's, explaining the reasoning behind the key choices, and staying honest about what is still to be confirmed with BRERC. Nothing here is fabricated: proposed items are flagged as such.

---

## 1. Project Understanding

BRERC is the Local Environmental Records Centre for the West of England — Bristol, Bath & North East Somerset, North Somerset and South Gloucestershire — and sits within Bristol City Council's Museums Service. It holds a large database of georeferenced biological records (OS British National Grid, varying precision) but has no public-facing way to explore them. This engagement builds a **public interactive species-records dashboard**, embedded on BRERC's own website, letting non-expert users browse where species have been recorded.

180DC Bristol is delivering this over an **~8-week engagement with 5 part-time student consultants**. The brief lists *potential* areas of work — **candidates, not commitments**; final scope is refined *with* BRERC (Tim Corner), not assumed. Two priorities are fixed: the **public dashboard is primary**, and an **internal staff monitoring dashboard is secondary and deferred**.

Two constraints dominate every decision. First, **data ethics (C2) is a hard stop**: records contain recorder personal data (`Recorder1`) and precise coordinates for sensitive/protected species, neither of which may reach the public. Second, the client app **must never touch PostgreSQL, hold credentials, or issue SQL** — it knows only an **API base URL** and talks to a team-owned backend. The dashboard is built against a development data subset now, then swapped to production at handover as a **configuration-only change (R6)**.

## 2. Objectives Mapped to Requirements

Every phase and step cites the requirement ID(s) it serves; there are no orphan features. **Primary requirements:** R1 public live dashboard on BRERC's site · R2 interactive grid-referenced species distribution maps · R3 species info + attributed/licensed images · R4 engaging accessible UX for the non-expert public · R5 WCAG 2.2 AA + published accessibility statement (**legal** — PSBAR 2018) · R6 live PostgreSQL with a config-only dev→prod credential swap · R7 documented, commented code + technical handover docs. **Secondary:** R8 internal staff monitoring dashboard. **Constraints:** C1 8-week, public-first scope refined with BRERC · C2 sensitive-species and recorder-PII/GDPR safety (**hard stop**) · C3 maintainable by BRERC staff post-handover.

## 3. Team Structure & Workstreams

Five part-time consultants, split around the API boundary so each can progress in parallel. **WS0 and WS1 owners are settled; WS2–WS4 owners are a proposal to confirm at the next team sync (before mid-review, 24 Jul).**

| WS | Scope | Owner |
|----|-------|-------|
| **WS0** | Lead, client liaison (Tim Corner), scope governance, integration, handover coordination | **Aman Shrivastava** (Project Leader) — *known* |
| **WS1** | Public dashboard **front-end** — React/TS/Vite, MapLibre maps, WCAG 2.2 AA, MSW-mocked API contract | **Michael Samuel** — *known; detailed below* |
| **WS2** | Backend API + geospatial serving — PostGIS parameterised queries, reproject EPSG:27700→4326, vector-tile/GeoJSON endpoints, **server-side sensitivity generalisation + PII stripping**, rate limiting | **Ming Chak (Victor) Sze** — *proposed, to confirm* |
| **WS3** | Database & data engineering — dev PostgreSQL from the sample, ETL/cleaning, grid-ref & date handling, data-quality checks, encoding the sensitivity policy | **Ting Ting He** — *proposed, to confirm* |
| **WS4** | Species content & enrichment — taxonomy, scientific vs common names, conservation status, Wikimedia imagery + attribution/licensing | **Athul Jomon** — *proposed, to confirm* |
| **WS5** | Internal monitoring dashboard (R8) | **Secondary / deferred** — only if the R1–R7 DoD is met and time permits |

The architectural boundary is strict: the proposed WS2 owns all data safety at source; WS1 renders only what is safe to render and adds client-side checks as **nets, not fixes**. This brief details **WS1 (Michael's front-end)** in full; WS2–WS4 appear as the flagged dependencies the front-end is built against.

## 4. Front-End Approach (WS1) & Data Ground Truth

The strategy is to **de-risk the single biggest schedule dependency** — the team's not-yet-built backend — by developing the entire front-end **contract-first** against a **mocked API**. The front-end defines the typed contract it needs, validates every response with **Zod** at the boundary, and serves it locally with **MSW (Mock Service Worker)** seeded from the *real sample shape*. Because the client only ever knows an API base URL, switching mock → real backend, and later dev → production, is a config change, never a code change.

**The dev data (ground truth).** The subset is a **19-column export ("main5" sample, ~900–1000 rows)**: `Scientific_Name`, `Common_Name`, `Grid_Ref` (BNG, **varying precision, 1 m–100 m**), `Place`, `Date_of_Record`, `Abundance`, `Sex_Stage`, `Record_Type`, `Precise_Date`, `Vague_Date`, `vitality`, `verified`, `YearEnd`, `Comments` (**free text**), `Source`, `unique_No`, `licence`, `Eastings`, `Northings` (**precise EPSG:27700 coords**). Critically, `Recorder1` (PII) and `BLISS` are named in the brief as fields of the *full* database but are **absent from this sample** — so the API contract must **explicitly exclude** them, never assuming sample-absence means production-absence.

**Phasing (P0–P8).** The plan is built public-first in small, requirement-traceable increments. It starts with foundations and C2/accessibility guardrails wired into CI *first* (P0), then a contract-first spine of PII-safe types, Zod schemas, a single API layer and the MSW mock (P1). P2 is a deliberately-rough **end-to-end SPIKE** — one honest species, map cells + species panel + accessible table — demoable at mid-review, exempt from the full Definition of Done *except* its C2 and core-accessibility hard gates. Later phases deepen the map centrepiece (P3), build species pages and imagery (P4), add search/filters (P5), then land the landing dashboard and the **legally-required accessibility statement** (P6). A dedicated real-API integration phase (P6.5) reconciles schema drift and **re-proves C2 on real responses**, followed by hardening, tests-in-CI and the handover runbook (P7). The internal dashboard (P8/R8) is deferred. The authoritative phase list is `docs/PLAN.yaml`, which the advisor can open directly.

**Critical path:** `P0 → P1 → P2 → P4 → P6 → P6.5 → P7`. The **legal accessibility statement (in P6) sits *on* the critical path** — a gating deliverable, never slack. P5 (search/filters) is deliberately *off* the critical path so it can be de-scoped without endangering the primary deliverable.

## 5. Key Decisions & Rationale

*The section the advisor asked to weigh most heavily: each choice states its* why*, and the rejected alternative where relevant.*

1. **Stack: React + strict TypeScript + Vite; MapLibre GL JS via `react-map-gl`; React Aria for UI.** *Why:* open-source mapping with **no proprietary API keys or per-view licence cost**, so BRERC can maintain it post-handover (C3); React Aria supplies **WCAG-compliant primitives**, so the *legal* accessibility duty (R5) is met *by construction*; a static SPA embeds cleanly on BRERC's site (R1). *Rejected:* proprietary BI/Tableau (licence cost, weak accessibility, not staff-maintainable); a bespoke accessible-widget layer (reinventing solved problems inside an 8-week budget).

2. **Honest grid/atlas cells at the record's *true* precision — not pin points.** *Why (scientific integrity):* UK biological records are grid-referenced at varying precision and are **effort-biased** — they show *where people looked*, not true distribution. Rendering a 100 m/1 km record as a single pin implies a false precision an ecologist or examiner would immediately flag. *Rejected:* plotting all records as uniform pins or snapping coarse (1 km) records onto a fine grid — both manufacture precision the source data does not have and would be flagged by an examining ecologist.

3. **Sensitivity & PII enforced server-side (C2 hard stop), with no per-record sensitivity marker.** *Why:* sensitive-species precise locations and recorder PII must **never reach the public client**; generalisation/suppression happens in *what the API returns*, not by hiding a layer the browser already downloaded. Crucially, sensitive records are **blended in indistinguishably** — a "sensitivity" flag would itself be a re-identification vector, letting an attacker enumerate protected cells (matching NBN Atlas / GBIF practice). Design detail: free-text **`Comments` withheld entirely**, **`Place` suppressed** for sensitive taxa, a **public precision floor**, and **low counts bucketed** (k-anonymity). *Rejected:* client-side filtering of downloaded precise coordinates (still a breach); a per-record sensitivity label (an attack surface, not a safeguard).

4. **Contract-first types + Zod validation at the boundary + TanStack Query for server state.** *Why:* a typed, validated contract makes **bad data fail loudly, not silently**; standard server-state handling (caching/retry/loading/error) avoids fragile, hand-rolled `fetch`-in-`useEffect` code that would be brittle at handover.

5. **MSW mock seeded from the real sample shape.** *Why:* WS1 can be **built and tested without waiting on WS2** — de-risking the single biggest schedule dependency — and because the client only ever knows an API base URL, the dev→prod switch (R6) becomes a **config-only change, never a code change**.

6. **Public-first phasing with a deliberately-rough mid-review SPIKE (P2).** *Why:* guarantees an **honest, demoable end-to-end slice by 24 July** without faking production quality; deferring R8 ensures the internal dashboard never competes with the primary public deliverable (C1).

7. **Accessibility as a build-blocker, not a finishing task (R5, legal).** *Why:* BRERC is a public-sector body; WCAG 2.2 AA and a published statement are a **legal duty** under PSBAR 2018. Includes a **non-map fallback (accessible table)** so no information is map-only, plus a keyboard-operable map. A ✗ on R5 blocks merge.

8. **No secrets in the client; env-driven config.** *Why:* anything in the browser bundle is public. DB credentials and tokens live **only** in the API environment; the client holds a public API base URL (and, pending Q4/Q5, a public map style/tile URL) via `VITE_*` (R6).

## 6. Timeline vs Milestones

Working against ~5 productive front-end weeks (assumption A15) between kick-off and the final presentation.

| Milestone | Date | WS1 position |
|-----------|------|--------------|
| Kick-off | 1 Jul 2026 | Scope confirmed; P0 foundations begun (branch `michael/phase-0-foundations`) |
| **Mid-project review** | **24 Jul 2026** | **P2 spike demoable** — one honest species (map + panel + accessible table), on mock data, C2 + core a11y hard-gated |
| Final presentation | w/c 10 Aug 2026 | Through P6/P6.5, accessibility statement published; P7 hardening under way |
| 180DC Showcase | 17 Aug 2026 | Hardened, documented, handover-ready; P8 (R8) only if slack remains |

A **dedicated integration phase (P6.5)** sits before the final presentation for real-API C2 re-proof. Phase sizing is back-solved against **~10–12 owner-hours/week** for one part-time consultant — an **assumption flagged in the plan (A15)**. If real hours differ, **phase depth flexes, DoD gates do not**: the de-scope order is (a) drop R8/P8, (b) cut P5 to a single species+year filter, (c) freeze P3 at GeoJSON + clustering and defer vector tiles — but **never** the accessibility statement or any C2/R5 gate.

## 7. Risks, Ethical Safeguards & Verification

**Top risks.**

- **RK1 — Backend/API (WS2) late or contract drifts when WS1 needs it** *(high / high).* Mitigated by the **MSW mock** (front-end builds without a backend) and a **dedicated P6.5 integration phase** to reconcile schema drift and re-prove C2.
- **RK12 — A single part-time front-end owner over-scopes and misses mid-review or final DoD** *(high / high).* Mitigated by the **deliberately-rough P2 spike** (DoD-exempt bar C2/R5), a **de-scopable P5**, and a **kill/keep gate** on secondary work.

**Ethical safeguards (C2 — hard stop).** Data ethics is merge-blocking, not a policy note. `Recorder1`/recorder PII never reach the client; `Comments` withheld entirely; `Place` suppressed for sensitive taxa; a public precision floor; low counts bucketed for k-anonymity; sensitive records blended indistinguishably (no marker). All enforcement is **server-side, in the proposed WS2/WS3**; WS1 adds a **CI grep-guard**, **contract tests** asserting `Recorder1`/`BLISS`/`Eastings`/`Northings`/`Comments`/any `sensitivity` marker are absent from parsed payloads, and **e2e wire inspection** re-run against the *real* API at P6.5 — as nets that catch regressions, while treating any client-side-only fix as a **contract bug to escalate**.

**How to verify this plan.** The front-end plan is a **machine-readable, machine-checkable artifact**, so the advisor can verify it independently rather than trust prose. From the repo root:

```bash
pip install pyyaml && python3 docs/validate_plan.py     # expect: 9/9 checks passed, exit 0
```

Artifacts: `docs/PLAN.yaml`, `docs/plan.schema.json`, `docs/validate_plan.py`. The validator independently confirms: the plan is schema-valid; **every R1–R8 + C1–C3 is covered**; no step cites an unknown requirement (**no orphan steps**); each step's requirements are a subset of its phase's; the `dependsOn` graph is **acyclic (a DAG)**; and — as a plan-level C2 net — **every client-facing endpoint's contract promises to exclude the PII/coordinate/sensitivity field set**. Assumption and risk ids (A15, RK1, RK12, …) are defined in `PLAN.yaml` under `assumptions[]` and `risks[]` and are covered by the validator's referential-integrity checks. Every phase and step cites its requirement ID(s), so the trace from requirement to code is explicit and auditable at handover.

## 8. Open Questions to Confirm with BRERC (Tim Corner)

The plan is deliberately honest about unknowns rather than inventing answers:

- **Q1–Q3 (C2 + R6):** the definitive **sensitive-taxa list** and per-tier generalisation resolution; **written confirmation** the API strips `Recorder1`/PII, withholds `Comments`, and excludes `BLISS`/`Eastings`/`Northings`; and that the server reprojects **27700 → 4326**, returning grid-cell geometry + precision via parameterised PostGIS queries.
- **Q4–Q5 (R2 / R1):** map delivery mode (**vector tiles vs GeoJSON**) and a **public-sector-licensed, CSP-compatible basemap** with no client-held secret.
- **Q6 (R1 / R5):** how the SPA **embeds on BRERC's website** (iframe vs mounted bundle vs sub-path) and the parent-page CSP/CORS/routing constraints.
- **Q7 (R3):** the **approved species-image source** and attribution/licensing policy.

These are tracked in the plan's `openQuestions[]` and form the agenda for the next BRERC scope conversation.

---

*This brief details WS1 to Definition-of-Done depth; WS2–WS4 and the full server contract are flagged proposals pending confirmation with the team and Tim Corner.*
