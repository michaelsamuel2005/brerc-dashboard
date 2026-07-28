# Project Structure 🗂️

> **Who is this for?** Everyone on the team. This is the map of our repository (our shared project folder on GitHub) — it tells you where everything lives and, most importantly, **where to put your own work** so the project stays tidy and easy to hand over to BRERC.
>
> New to Git and GitHub? Start with [**docs/GETTING_STARTED_GITHUB.md**](GETTING_STARTED_GITHUB.md) first, then come back here. (*Git* is the tool that tracks changes to our files; *GitHub* is the website where we store and share them.)

---

## 📁 The repository at a glance

Our project is a **monorepo** — that just means one single shared repository holds everything together: the front-end, the back-end, the internal tool, the database definitions, and all our documentation, side by side in one place. Here is the top-level layout:

```text
brerc-dashboard/
├── web/            # 🌐 PUBLIC front-end dashboard (React + TypeScript + Vite) — the main deliverable
├── api/            # 🔌 BACK-END API — talks to the database, serves safe data to web/
├── internal-web/   # 🛠️  INTERNAL staff data-quality dashboard (secondary, if time permits)
├── db/             # 🗄️  DATABASE schema & migrations (PostgreSQL / PostGIS)
├── docs/           # 📚 All shared documentation (you are here)
├── data/           # 🔒 Local sample data — GIT-IGNORED, never committed
├── .github/        # ⚙️  GitHub templates (e.g. the pull-request template)
├── README.md       # Project overview and starting point
├── CONTRIBUTING.md # How we work together (branches, pull requests, reviews)
├── CODE_OF_CONDUCT.md
└── LICENSE
```

> 💡 **A few words you'll see a lot:**
> - **Front-end** = the part people see and click in their web browser (the public website).
> - **Back-end** = the behind-the-scenes part that fetches and prepares data; visitors never see it directly.
> - **API** = the doorway the front-end uses to ask the back-end for data.
> - **Database** = where all the records are actually stored.

> 🔑 **One rule above all others:** real or sensitive BRERC data must **never** enter Git — not in `data/`, not anywhere. See [Where do I put…?](#-where-do-i-put) below.

---

## 🧩 The code areas

Each area will have its own README with the detail. This table is the quick summary.

> ℹ️ **Note on the links below.** Some per-folder READMEs are still being written, so a few links may not open yet. They point to where each README **will** live, so this table stays correct as the folders fill in.

| Folder | What it's for | Owner | Status |
| --- | --- | --- | --- |
| [`web/`](../web/README.md) | The **public dashboard** — the interactive, accessible website that shows BRERC's species and environmental records to the public. React + TypeScript, built with Vite. **This is our primary deliverable.** | **Michael** | 🟢 In progress |
| [`api/`](../api/README.md) | The **back-end API**. It connects to the database, keeps sensitive data safe, and serves only clean, public-safe data to `web/` over HTTPS/JSON. | **[TO BE CONFIRMED]** (a teammate) | 🟡 Folder exists — early / not yet started |
| [`internal-web/`](../internal-web/README.md) | The **internal data-quality tool** for BRERC staff. Helps them monitor the content and quality of their database. **Secondary** — only built if time allows. | **[TO BE CONFIRMED]** | 🟡 Folder exists — early / not yet started |
| [`db/`](../db/README.md) | The **database definitions** — schema and migrations for the PostgreSQL / PostGIS database. (*Schema* = the shape of the data; *migrations* = tracked, ordered changes to that shape.) | **[TO BE CONFIRMED]** | 🔵 Planned — folder not created yet |

> 📝 **A note on status.** Right now, `api/` and `internal-web/` exist but are essentially empty, and `db/` and `data/` haven't been created yet — that's all expected at this stage. If you pick up one of these areas, create the folder (if it isn't there yet), add a short `README.md` describing it, and let the team know on your branch's pull request (see [How we work](#-a-reminder-on-how-we-work)).

---

## 🔗 How the pieces fit together

The three code areas talk to each other in a deliberate, one-directional chain — and this order matters for **security** and for our **legal accessibility duty** as a public-sector project.

```text
   Public visitor
        │  (uses the website in their browser)
        ▼
   ┌─────────┐   HTTPS / JSON   ┌─────────┐   secure connection   ┌────────────┐
   │  web/   │ ───────────────▶ │  api/   │ ────────────────────▶ │  database  │
   │ front-  │ ◀─────────────── │ back-   │ ◀──────────────────── │ (shape     │
   │  end    │   safe data only │  end    │    real data          │  set in db/│
   └─────────┘                  └─────────┘                       └────────────┘
```

- **`web/` (front-end)** runs in the public's browser. It asks `api/` for data over **HTTPS/JSON** — that is, over a secure web connection, in a simple text format both sides understand — and draws the maps, species pages, and charts.
- **`api/` (back-end)** is the *only* part that connects to the database. It runs **parameterised queries** (a safe way of asking the database for data that blocks a common form of attack), strips out anything sensitive (personal data, precise locations of protected species), and returns only public-safe data.
- **`db/`** holds the database's schema and migrations — the definition of how the data is stored.

> 🔒 **Critical boundary:** the public front-end (`web/`) **never connects to the database directly** and holds **no credentials and no real data**. (*Credentials* = the passwords/keys that unlock the database.) Everything sensitive is filtered out on the back-end, inside `api/`, before it ever reaches a visitor's browser. This is not optional: data protection is a legal duty, and accessibility (**WCAG 2.2 AA** — the legally required accessibility standard for UK public-sector websites) applies to everything we ship in `web/`.

---

## 🧭 Where do I put…?

Use this table before you start a new piece of work. When in doubt, ask on your pull request.

| I want to add… | Put it in… | Notes |
| --- | --- | --- |
| A new **front-end component / page / style** | `web/src/…` | For example a components or features folder inside `web/src/`. Owner: Michael. |
| A new **API endpoint** or back-end logic | `api/…` | The back-end owns all database access and all query logic. |
| A change to the **internal staff tool** | `internal-web/src/…` | Secondary — check priorities with the team first. |
| A **database change** (new table, column, migration) | `db/…` | Schema and migrations only — never real data. Create `db/` if it doesn't exist yet. |
| **Documentation** (guides, notes, decisions) | `docs/…` | Keep it in Markdown and cross-link where helpful. |
| **Sample data** for local testing | `data/` | 🔒 **GIT-IGNORED** (Git is set to ignore this folder, so nothing in it is ever uploaded). Kept only on your own machine — see [`data/README.md`](../data/README.md). Create `data/` locally if it doesn't exist yet. |
| **Real or sensitive BRERC data** | ❌ **Nowhere in Git** | Never commit it — not in `data/`, not anywhere. Real data stays out of the repository entirely. |
| A **secret** (password, API key, database credential) | ❌ **Nowhere in Git** | Secrets live only in server environment configuration, never in the code. |

> ⚠️ **If you're not sure whether something is safe to commit, don't commit it — ask first.** (*Commit* = to save a change into Git's history.) It's far easier to check beforehand than to remove sensitive data from Git's history later.

---

## 🌱 A reminder on how we work

- Work on your **own branch** — never directly on `main`. (A *branch* is your own private copy to work on; `main` is the shared, always-working version.) Branch names follow `<your-name>/<short-topic>`, e.g. `michael/map-legend`.
- **Pull `main`** before starting new work so you're up to date. (*Pull* = download the latest changes from GitHub.)
- Push your branch and open a **pull request** (a request for a teammate to review and merge your work); a teammate reviews it before it merges.
- Keep `main` working at all times.
- **Never commit secrets or data files.**

New to any of this? The step-by-step walkthrough is in [**docs/GETTING_STARTED_GITHUB.md**](GETTING_STARTED_GITHUB.md), and our shared conventions live in [**CONTRIBUTING.md**](../CONTRIBUTING.md).

---

## 🔎 Related documentation

| Document | What's in it |
| --- | --- |
| [README.md](../README.md) | Project overview, team, milestones |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | How we collaborate |
| [docs/README.md](README.md) | Index of all documentation |
| [docs/GETTING_STARTED_GITHUB.md](GETTING_STARTED_GITHUB.md) | Zero-knowledge Git & GitHub guide |
| [docs/MAINTAINER_GUIDE.md](MAINTAINER_GUIDE.md) | Guide for the BRERC maintainer after handover |
| [web/README.md](../web/README.md) · [api/README.md](../api/README.md) · [internal-web/README.md](../internal-web/README.md) · [db/README.md](../db/README.md) · [data/README.md](../data/README.md) | Per-folder details |

> ℹ️ Some details — exactly how and where the dashboard is hosted, the precise data-update mechanism, the owners of `api/`, `internal-web/` and `db/`, and the final handover contact — are **[TO BE CONFIRMED]** as the project progresses. This document will be updated as those decisions are made.
