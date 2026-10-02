# Accessibility mutation runner

Run only through:

```bash
npm run a11y:mutate
```

The wrapper copies the current `web/` snapshot to a system temporary directory, installs
dependencies in that copy, runs the focused operator sweep there, verifies the original
inputs did not change, and atomically writes JSON and Markdown reports under the ignored
`test-results/a11y-mutation/` directory.

For a quick harness check that intentionally produces no score:

```bash
python3 mutation/run_disposable.py --max-mutants 1
```

The result is a focused score for the listed operators and sources, not a general
TypeScript mutation score. A complete run excludes invalid TypeScript mutants from the
denominator and refuses to publish a score when any mutant timed out or was inconclusive.
