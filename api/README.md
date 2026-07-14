# 🔌 api/ — Back-end API

The **back-end API**. It talks to the database, and serves only **safe,
non‑sensitive data** to the front‑end over HTTPS.

**Owner:** [TO BE CONFIRMED]
**Status:** 🟡 In development

> 🔒 **This is the safety boundary.** The API decides what leaves the database.
> It must **never** expose precise locations of sensitive species or any personal
> data (e.g. recorder names). Filter, generalise, or remove that data here — the
> front‑end can only show what this layer sends it.

## What goes here

- API endpoints that the front‑end calls.
- Database queries (parameterised — never build SQL by pasting in user input).
- The logic that strips or generalises sensitive data before it is served.

## What does **not** go here

- ❌ Front‑end / UI code — that lives in `../web`.
- ❌ The database schema itself — that lives in `../db`.
- ❌ Real secrets or `.env` files committed to git — keep credentials out of the repo.

## Helpful links

- 🗂️ [Project structure](../docs/PROJECT_STRUCTURE.md) — what every folder is for.
- 🐙 [Getting started with GitHub](../docs/GETTING_STARTED_GITHUB.md) — branch, push, open a PR (no prior experience needed).
