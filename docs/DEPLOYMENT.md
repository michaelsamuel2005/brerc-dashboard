# Deploying the public dashboard

**Audience:** whoever installs and runs this — not necessarily a developer.
**Shape:** the dashboard runs as its own service at its own address, and BRERC's
website links to it. See "Why a subdomain" below.

---

## What runs where, and why it matters

There are **two databases**, and keeping them apart is the whole safety design.

| | Holds | Who reads it | Where it runs |
|---|---|---|---|
| **Source database** | BRERC's full records — precise coordinates, recorder names, sensitive species | The loader, read-only, over TLS | BRERC's internal network |
| **Publication database** | Only what a release published — generalised locations, no recorder names, no precise coordinates | The API, read-only | Wherever the dashboard is hosted |

The **loader** is the only component that touches the source. It reads, applies
the safety boundary, and writes a candidate release into the publication
database, which becomes visible in one atomic step. Nothing else ever connects
to the source.

This is why the dashboard does not have to run inside BRERC's network. The
publication database contains no personal data and no precise locations —
that is enforced in the database itself, not by convention. **The loader must
run where the source is reachable; the dashboard need not.**

If BRERC would rather host everything internally, the same stack runs there
unchanged. Only the address changes.

---

## Why a subdomain, and not a page on the website

BRERC's website serves pages. This dashboard is a running application with a
database behind it, so it needs a service of its own with an address that
points at it.

BRERC already does this twice: **recording.brerc.org.uk** for online recording,
and **imaps.brerc.org.uk** for the species data portal. A dashboard at, say,
`map.brerc.org.uk` is the same pattern a third time — not a new kind of thing.

The website then links to it, so visitors reach it from BRERC's own navigation.
The link markup is at the end of this document.

---

## What BRERC needs to provide

1. **A hostname** — e.g. `map.brerc.org.uk` — with DNS pointing at the host
   this stack runs on, and ports 80 and 443 reachable from the internet.
   Caddy obtains and renews the HTTPS certificate automatically; nobody has to
   remember to renew anything.
2. **A host to run it on** — any Linux machine with Docker. The stack is three
   containers.
3. **A connection for the loader to BRERC's source view**, read-only, over TLS.
   This is the separate scheduled job, not part of this stack.

---

## Installing

```bash
cp deploy/.env.example deploy/.env
# edit deploy/.env — every value is required, none has a working default
cd deploy && docker compose up --build -d
```

Then check it is healthy:

```bash
curl -fsS https://map.brerc.org.uk/api/health     # {"status":"ok",...}
```

The first release must be loaded before the dashboard shows anything. Until
then the API answers **503 "No active publication release"** — this is the
correct response, not a fault. It distinguishes "nothing published yet" from
"broken", which an empty page would not.

### What each value in `.env` does

| Name | Meaning |
|---|---|
| `SITE_ADDRESS` | The public hostname. Caddy gets a certificate for it. Use `:80` for a local run with no certificate. |
| `POSTGRES_PASSWORD` | Superuser password for the publication database. Never leaves the host. |
| `API_DB_PASSWORD` | Password for the API's read-only login. |
| `APP_ENV` | `prod` in deployment. Hides the interactive API docs and refuses to start without a database URL. |
| `ALLOWED_ORIGINS` | **Leave empty.** See below. |

### Why `ALLOWED_ORIGINS` is empty

The app and the API are served from the same address through the proxy, so the
browser never makes a cross-origin request and no CORS permission is needed.
Verified: with `APP_ENV=prod` and no origins configured, the dashboard works
normally and the API returns no cross-origin headers to any caller.

If someone later splits the app and API onto different hostnames, this list has
to be filled in — which is the point of leaving it empty. The safe default
fails closed.

---

## Upgrading and rolling back

```bash
git pull && cd deploy && docker compose up --build -d
```

Data lives in Docker volumes (`db_data`, `caddy_data`), so containers can be
rebuilt freely without touching the published release. To roll the application
back, check out the previous commit and run the same command; the publication
database is unaffected because the API only reads it.

**Restoring a previous release** is a different operation and is handled by the
loader, not by redeploying — the release history lives in the database.

---

## Backups

Back up the publication database on whatever schedule BRERC uses:

```bash
docker compose exec db pg_dump -U postgres brerc_publication | gzip > backup.sql.gz
```

It can also be rebuilt from the source by re-running the loader, so a lost
backup is recoverable — but only while the source database still holds the same
records.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `503 No active publication release` | Nothing published yet, or the last release was not activated. Correct behaviour, not a fault. |
| Certificate not issued | DNS is not pointing here yet, or ports 80/443 are not reachable. Caddy retries. |
| API will not start in `prod` | `DATABASE_URL` is unset. Deliberate: it refuses rather than falling back to a local database. |
| Dashboard loads, data does not | Check `/api/health` first. If that is fine, the release is likely inactive. |

---

## The link for BRERC's website

Paste into the navigation of `www.brerc.org.uk`, alongside the existing links
to recording and the data portal:

```html
<a href="https://map.brerc.org.uk/">Species distribution map</a>
```

Notes for whoever adds it:

- **Same tab, no `target="_blank"`.** Opening a new tab unexpectedly is a known
  accessibility problem, and the dashboard is BRERC's own service, not an
  external site.
- If it must open in a new tab, add `rel="noopener"` and say so in the link
  text, e.g. "Species distribution map (opens in a new tab)", so screen-reader
  and switch users are told before they activate it.
- No `nofollow` — this is BRERC's own content and should be indexable.
