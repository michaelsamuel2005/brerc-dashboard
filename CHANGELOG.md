# Changelog

All notable changes are documented here. Format:
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning:
[SemVer](https://semver.org/spec/v2.0.0.html) once a first release is cut.

## [Unreleased]

### Added
- Repository **foundation** for the BRERC dashboard: complete plumbing — folder
  structure, `docker-compose`, `Makefile`, CI/CD (GitHub Actions), CodeQL,
  Dependabot, community-health files, and all tooling configs — with the core
  logic left as guided `TODO` **stubs**.
- **`BUILD_PLAN.md`** — the ordered, step-by-step plan to implement the dashboard
  (database → gate → tiles → API → front end → internal tool → ship).
- Governance and decisions documented up front (`docs/DATA_GOVERNANCE.md`,
  `docs/DECISIONS.md`); other docs are skeletons to complete as you build.

### Notes
- Licensed **MIT** (a default; the final choice rests with BRERC / 180DC — see
  `docs/DECISIONS.md`).
- Synthetic data and stubs only: no client data, no secrets. The authoritative
  sensitive-species list goes into the database, never into this repository.
