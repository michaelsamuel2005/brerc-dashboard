<!--
  Thanks for contributing. Keep PRs small and focused. Explain the WHY for the
  next maintainer (BRERC staff may maintain this), not just the what.
-->

## What and why

<!-- What does this change, and why? Link the issue if there is one. -->

## Governance & accessibility checklist

Tick what applies; delete rows that genuinely don't (don't just ignore them).

- [ ] **No client data** committed. Only the synthetic seed under `db/seed/` is versioned; `data/` and `.env` are untouched.
- [ ] **No secrets** added to code, config, or history.
- [ ] **The gate still holds.** If I touched the DB, tiles, or API, `make gate-test` passes and no public path can return finer-than-allowed geometry or recorder PII.
- [ ] **Read-only preserved.** No new write path; SQL is parameterised; queries are bounded.
- [ ] **Accessibility (WCAG 2.2 AA).** No new `eslint-plugin-jsx-a11y` or `jest-axe` violations; keyboard + focus still work; the data-table equivalent still matches the map.
- [ ] **Image licensing.** Any new image path stays fail-closed (licence + attribution or a placeholder).
- [ ] **Tests added/updated** for new logic, and the suite is green.
- [ ] **Docs updated** if behaviour changed.

## How I tested

<!-- Commands run, what you saw, screenshots for UI changes. -->
