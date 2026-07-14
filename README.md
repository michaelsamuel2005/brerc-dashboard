# 🌿 BRERC Dashboard

**An accessible, public dashboard for the West of England's environmental and species‑records data.**

A team project by **180 Degrees Consulting Bristol** for the **Bristol Regional
Environmental Records Centre (BRERC)**.

![Status: in development](https://img.shields.io/badge/status-in%20development-f0ad4e)
![Licence: MIT](https://img.shields.io/badge/licence-MIT-2e7d32)
![180DC Bristol](https://img.shields.io/badge/180DC-Bristol-1b5e20)

> This is the team's shared repository. How we build it — the tools, folder
> structure, and implementation — is decided together as the project develops.

---

## 📖 About the project

The **Bristol Regional Environmental Records Centre (BRERC)** is the Local
Environmental Records Centre for the West of England — Bristol, Bath & North East
Somerset, North Somerset, and South Gloucestershire. It collects and shares the
biodiversity and geodiversity records that underpin research, conservation, and
planning across the region.

Working with BRERC, our team is building tools to help present this data to the
public and to help BRERC keep it high‑quality.

## 🎯 Goals

- 🗺️ **Public dashboard** — an engaging, user‑friendly, and **accessible**
  dashboard for BRERC's website, featuring interactive species‑distribution maps
  with species information and images.
- 🔎 **Internal data‑quality tool** *(secondary)* — help BRERC staff monitor the
  content and quality of their database.
- 📚 **Documentation** — well‑documented work so BRERC can maintain and extend it.

_Scope is refined together with BRERC as the project progresses._

> ♿ **Accessibility is a legal requirement.** BRERC is a public‑sector body, so
> the public dashboard must meet **WCAG 2.2 AA**. We build with that standard in
> mind from the start.

## 👥 The team

| Member | Role |
| --- | --- |
| **Aman** | Project Leader |
| **Athul** | Consultant |
| **Michael** | Consultant |
| **Ting Ting** | Consultant |
| **Victor** | Consultant |

## 📇 Key contacts

| Name | Role | Organisation |
| --- | --- | --- |
| **Tim Corner** | Manager | BRERC |
| **Jaslyn Leong** | Reviewer | 180 Degrees Consulting Bristol |

## 🗓️ Milestones

| Date | Milestone |
| --- | --- |
| 1 Jul 2026 | Kick‑off |
| 24 Jul 2026 | Mid‑project review |
| w/c 10 Aug 2026 | Final presentation |
| **17 Aug 2026** | **Bristol 180DC Showcase** |

## 📁 Repository structure

This is a single shared **monorepo** — that is, one repository that holds every
part of the project, each in its own top‑level folder. Full details are in
**[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)**.

```text
brerc-dashboard/
├── web/            # 🌐 Front‑end: the public dashboard (React / TypeScript / Vite)
├── api/            # 🔌 Back‑end API: talks to the database, serves safe data to the front‑end
├── internal-web/   # 🔧 Internal staff data‑quality dashboard (secondary)
├── db/             # 🗄️ Database schema & migrations (PostgreSQL / PostGIS)
├── docs/           # 📚 Shared documentation
├── data/           # ⚠️ Local sample data — git‑ignored, NEVER committed
└── .github/        # ⚙️ GitHub templates (pull‑request template)
```

| Folder | Purpose |
| --- | --- |
| **`web/`** | The public dashboard front‑end. |
| **`api/`** | The back‑end API that reads the database and serves only safe, public data. |
| **`internal-web/`** | The internal data‑quality tool for BRERC staff *(secondary)*. |
| **`db/`** | Database schema and migrations. |
| **`docs/`** | All shared project documentation. |
| **`data/`** | Local sample data — **git‑ignored and never committed**. |

> ⚠️ **Never commit real or sensitive data.** The `data/` folder is git‑ignored
> on purpose. Environmental records can include sensitive or personal
> information, so raw data files must never enter git.

## 🚀 Getting started

> 🆕 **New to Git or GitHub?** Don't worry — you're very welcome here. Start with
> **[docs/GETTING_STARTED_GITHUB.md](docs/GETTING_STARTED_GITHUB.md)**, a
> step‑by‑step walkthrough written for complete beginners. It explains every
> command below in plain English, so come back here once you've read it.

First, make your own copy of the project on your computer (this is called
"cloning"):

```bash
git clone https://github.com/michaelsamuel2005/brerc-dashboard.git
cd brerc-dashboard
```

Always do your work on your own **branch** (a personal, separate copy of the
project's files where your changes stay until they're reviewed) — never directly
on `main`. When you're ready, open a **pull request** so a teammate can review
your work before it's merged. Full details are in
**[CONTRIBUTING.md](CONTRIBUTING.md)**.

```bash
# Create and switch to your own branch:
git switch -c <your-name>/<short-topic>

# ...do your work, then save it...

# Send your branch up to GitHub so others can see it and review it:
git push -u origin <your-name>/<short-topic>
```

## 📚 Documentation

| Guide | What it's for |
| --- | --- |
| **[docs/GETTING_STARTED_GITHUB.md](docs/GETTING_STARTED_GITHUB.md)** | New to GitHub? Start here — a zero‑prior‑knowledge walkthrough. |
| **[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)** | How the repository is organised and what each folder does. |
| **[docs/MAINTAINER_GUIDE.md](docs/MAINTAINER_GUIDE.md)** | For the BRERC staff member who maintains the dashboard after handover. |
| **[CONTRIBUTING.md](CONTRIBUTING.md)** | How we branch, review, and merge. |

More documentation lives in **[docs/](docs/)**.

## 🤝 Contributing & conduct

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how we branch, review, and merge.
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — how we work together respectfully.

## 📄 Licence

Released under the [MIT Licence](LICENSE).
