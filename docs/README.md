# Documentation index

Start with the repository [`README.md`](../README.md), then use these:

| Document | What it covers |
|----------|----------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The shape of the system, why each technology was chosen, and why a custom front end over Streamlit/Panel/Dash/Shiny. |
| [DATA_MODEL.md](DATA_MODEL.md) | Tables, the `public_occurrences` gate, roles, CRS, and grid-reference precision. Marks confirmed fields vs assumptions. |
| [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) | The binding rules (sensitive locations, recorder PII, image licensing, accessibility, security) and how each is enforced + tested. |
| [SENSITIVE_SPECIES.md](SENSITIVE_SPECIES.md) | The generalisation gate in detail: how locations are blurred, the control list, and what the gate test asserts. |
| [ACCESSIBILITY.md](ACCESSIBILITY.md) | The WCAG 2.2 AA plan, the map-exemption nuance, and how accessibility is tested. |
| [ACCESSIBILITY_STATEMENT.md](ACCESSIBILITY_STATEMENT.md) | A gov.uk-model accessibility statement **template** for BRERC to complete and publish. |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Running locally and in production; embedding, TLS, basemap, and scaling. |
| [HANDOVER.md](HANDOVER.md) | The dev→prod credentials-only runbook, routine maintenance, and the pre-publication checklist. |
| [INTERNAL_DASHBOARD.md](INTERNAL_DASHBOARD.md) | The secondary internal data-quality dashboard: what it shows, how it is isolated, and how to enable it. |
| [DECISIONS.md](DECISIONS.md) | The settled decisions (D-001…D-008) and their rationale. |

Governance and compliance are the authority for anything touching published
data, locations, personal data, images, or the public UI.
