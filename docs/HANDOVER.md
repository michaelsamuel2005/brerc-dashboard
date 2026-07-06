# Handover runbook

> **Skeleton — fill this in as the system settles (see `BUILD_PLAN.md`).**
> Reference: Learning Guide Module 8 · Answer Key: `brerc-public-dashboard/docs/HANDOVER.md`

## Dev → production is a credentials change
The app connects with one read-only URL. To point it at BRERC production, change
`PUBLIC_DATABASE_URL` (and Martin's `DATABASE_URL`) to BRERC-supplied **read-only**
credentials — no code changes. Document the exact steps here once confirmed.

## TODO
- [ ] Routine maintenance (Dependabot, sensitive-list updates, backups).
- [ ] Troubleshooting (blank tiles → restart Martin; API 500s → check the URL/view).

## Pre-publication checklist
Before making the repository public **or** launching the dashboard, confirm:

- [ ] **Sign-off** from BRERC (Tim Corner) and the 180DC leads (Aman, Jaslyn).
- [ ] **No client data in history** (`git log -p -- data/` empty).
- [ ] **No secrets in history** (no `.env`, keys, or passwords committed).
- [ ] **No authoritative sensitive-species list committed** — synthetic demo only.
- [ ] **Licence** confirmed (`LICENSE`).
- [ ] **CI green**, including the database gate job.
- [ ] **`frame-ancestors`** in `proxy/Caddyfile` set to BRERC's real host(s).
- [ ] **Accessibility statement** completed and published.
- [ ] **CODEOWNERS** handles replaced with the team's real GitHub usernames.
- [ ] **Branch protection** on `main` (require PR + passing CI).
