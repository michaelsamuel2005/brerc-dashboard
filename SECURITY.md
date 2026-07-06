# Security & data-protection policy

This project handles biodiversity records on behalf of a public-sector client.
Two categories of risk are treated as **incidents**, not bugs:

1. **Sensitive-species location disclosure** — any path that could emit precise
   coordinates, precise grid references, point markers, or raw downloads for a
   sensitive-list species, a badger sett, or a Schedule 1 bird nest site.
2. **Personal-data or secret disclosure** — recorder names (`Recorder1`) or any
   personal data on the public tier; or credentials/secrets committed to the
   repository.

## Reporting a vulnerability

Please **do not open a public issue** for either category above. Instead:

- Contact the dashboard owner (Michael) and the 180DC Project Leader (Aman)
  directly, and — for anything touching sensitive-species or personal data —
  the BRERC Manager (Tim Corner), so BRERC can assess data-agreement impact.
- Include the smallest reproduction that demonstrates the issue **without**
  pasting real client data into any third-party tool, chat, or issue tracker.

For ordinary, non-sensitive bugs, a normal issue or pull request is fine.

## If real data or a secret was committed

1. Treat it as a live incident; notify the people above immediately.
2. Rotate any exposed credential at once (it must be considered compromised even
   after removal — git history is distributed).
3. Purge it from history (e.g. `git filter-repo`) and force-push **only** after
   coordinating with the team; every clone must be re-based or re-cloned.
4. If the repository is public, assume the data/secret is already scraped: the
   priority is rotation and BRERC notification, not deletion alone.

## Controls already in place

- `data/` and `.env*` are git-ignored (`.gitignore`); only synthetic seed data
  is committed.
- The application uses a **read-only** database role; the API is GET-only, uses
  parameterised SQL, statement timeouts, and row caps.
- Sensitive-species generalisation is enforced **server-side and fail-closed**
  in the `public_occurrences` view, and covered by an automated gate test.
- CI runs dependency and (optionally) secret scanning on every pull request.

See [`docs/DATA_GOVERNANCE.md`](docs/DATA_GOVERNANCE.md) for the binding rules.
