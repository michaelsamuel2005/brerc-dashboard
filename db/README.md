# 🗄️ db/ — Database Schema & Migrations

The **database schema and migrations** for the project (PostgreSQL / PostGIS).

**Owner:** [TO BE CONFIRMED]
**Status:** 🟡 In development

> 🧭 This folder describes the **shape** of the database (tables, columns,
> spatial types, migrations) — not the data itself, and not credentials.

## What goes here

- Schema definitions and migration files.
- PostGIS setup for spatial (map) data.
- Notes on how the database is structured.

## What does **not** go here

- ❌ Real or sample data rows — see `../data` (git‑ignored).
- ❌ Database passwords, connection strings, or `.env` files — never commit secrets.
- ❌ Application code — the API that queries the database lives in `../api`.

## Helpful links

- 🗂️ [Project structure](../docs/PROJECT_STRUCTURE.md) — what every folder is for.
- 🐙 [Getting started with GitHub](../docs/GETTING_STARTED_GITHUB.md) — branch, push, open a PR (no prior experience needed).
