# 🌿 web/ — Public Dashboard (front-end)

The **public, accessible dashboard** for BRERC's website — interactive
species‑distribution maps with species information and images. Built with
**React + TypeScript + Vite**.

**Owner:** Michael (Consultant)
**Status:** 🟡 In development

> ♿ **Accessibility is a legal requirement.** BRERC is a public‑sector body, so
> this dashboard must meet **WCAG 2.2 AA**. Keep every feature keyboard‑operable,
> properly labelled, and usable without a mouse.

## What goes here

- The front‑end app: React components, pages, styles, and the map UI.
- Anything that runs in the user's browser.

## What does **not** go here

- ❌ **No database access and no secrets.** The front‑end only talks to the
  back‑end API (`../api`) over HTTPS. It never connects to the database and never
  holds credentials.
- ❌ No real or sensitive data — see `../data`.
- ❌ Back‑end logic — that lives in `../api`.

## Helpful links

- 🗂️ [Project structure](../docs/PROJECT_STRUCTURE.md) — what every folder is for.
- 🐙 [Getting started with GitHub](../docs/GETTING_STARTED_GITHUB.md) — branch, push, open a PR (no prior experience needed).
