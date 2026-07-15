# Contributing

Welcome! This is the team's shared workflow. Keep it simple, and let's agree any extra conventions together.

> 🌱 **New to Git or GitHub?** Read [`docs/GETTING_STARTED_GITHUB.md`](docs/GETTING_STARTED_GITHUB.md) first — it walks you through everything from scratch, assuming zero prior knowledge. Come back here when you're ready.

> 🔑 **Golden rule: never commit directly to `main`.** Always do your work on your own **branch** (your own private copy of the project), then open a **pull request** (a request to merge your work in) so a teammate can review it before it joins `main`. This keeps `main` working for everyone.

## The workflow: branch → pull request → merge

Follow these steps in order every time you start a new piece of work:

1. **Switch to `main` and get the latest version** so you start in sync with everyone else:
   ```
   git switch main
   git pull
   ```
2. **Create your own branch** to work on (this leaves `main` untouched):
   ```
   git switch -c <your-name>/<short-topic>
   ```
3. **Make focused commits** as you go. A *commit* is a saved snapshot of your changes — write a short message saying *what* changed and *why*.
4. **Push your branch** to GitHub (upload your work) and **open a pull request**.
5. **A teammate reviews** your pull request, then it's merged into `main`. Don't merge your own work without a review, and keep `main` in a working state.

> New to these commands? Don't worry — [`docs/GETTING_STARTED_GITHUB.md`](docs/GETTING_STARTED_GITHUB.md) explains each one step by step.

### Branch naming

Name your branch `<your-name>/<short-topic>` — all lowercase, with words joined by hyphens. For example:

- `michael/map-legend`
- `ting-ting/species-search`

## Pull-request checklist

Before you ask for a review, quickly check that your pull request:

- [ ] Has a **clear description** of what changed and why.
- [ ] Will be **reviewed by a teammate** before it merges (don't merge your own work).
- [ ] **Doesn't break others' work** — `main` should always still run.
- [ ] Contains **no secrets and no data files** — real or sensitive data must **never** enter git (see [`data/README.md`](data/README.md)).

## Good habits

- Pull `main` before starting new work so you stay in sync with the team.
- Keep changes small and focused — it makes reviews faster and kinder.
- Don't commit secrets (like passwords or keys) or large/raw data files.

> ♿ Accessibility (**WCAG 2.2 AA**) is a **legal requirement** for this public-sector dashboard. If your change touches the front-end (`web/`), keep it keyboard-operable and accessible.

Thanks for helping keep the project tidy and welcoming! 💚
