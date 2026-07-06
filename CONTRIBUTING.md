# Contributing

Thanks for working on the BRERC public dashboard. This is a client deliverable,
so the bar is production quality and the governance rules are non-negotiable.

## Golden rules (read first)

1. **Never commit client data.** `data/` is git-ignored. Only the synthetic seed
   in `db/seed/` is version-controlled. If you need realistic volume, generate
   more synthetic data with `scripts/seed_synthetic.py`.
2. **Never commit secrets.** Credentials live in a git-ignored `.env`.
3. **Public read paths select from `public_occurrences` only** — never from the
   precise `occurrences` table. If you add a public endpoint or tile, it must go
   through the generalised view, and the gate test must still pass.
4. **Accessibility is a requirement, not a polish step.** New UI must keep the
   interface at WCAG 2.2 AA (keyboard, focus, contrast, names/roles) and keep an
   accessible non-map equivalent for any essential map information.

## Workflow

- Branch from `main`: `feat/…`, `fix/…`, `docs/…`, `chore/…`.
- Keep pull requests small and focused; fill in the PR template.
- `main` is protected: every change lands via reviewed pull request.
- Communication with BRERC is coordinated through the 180DC Project Leader
  (Aman) and Head of Data Science (Jaslyn) — don't contact the client directly
  without sign-off.

## Local checks (run before pushing)

```bash
make lint          # ruff + eslint + sqlfluff
make typecheck     # mypy + tsc --noEmit
make test          # api unit tests + web unit/a11y tests
make gate-test     # the fail-closed sensitive-species gate (needs the DB up)
```

CI runs the same checks on every pull request (`.github/workflows/ci.yml`).

## Commit style

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `test:`, `chore:`,
`refactor:`). Reference an issue where one exists. Write commit bodies for the
next maintainer — which, per the brief, may be a non-developer at BRERC.

## Code conventions

See [`CLAUDE.md`](CLAUDE.md). In short: comment for a non-developer maintainer,
use the canonical names from `docs/` (e.g. `public_occurrences`, `EPSG:27700`,
Martin, MapLibre GL JS), add tests for new logic, and prefer clarity over
cleverness.
