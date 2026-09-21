# Production serving and Linux validation

This package is the reviewed **team-owned deployment procedure** for serving an
immutable BRERC dashboard release on a BRERC-operated Linux host. Every tracked
unit and nginx file is an inert `.example`: cloning the repository installs,
starts and schedules nothing. BRERC remains responsible for its host, DNS, TLS
certificates, database, secrets, backups, firewall, monitoring and operators.

This procedure does not use the repository-root `docker-compose.yml`, the old
root `Caddyfile`, the obsolete schema or a mutable checkout. Those development
artifacts are not a production deployment. It also does not publish Martin or a
`/tiles` route. A future tile architecture is a separately reviewed decision.

## Reviewed topology

```text
Internet browser
  -> public nginx :443
       -> immutable web/dist files
       -> /api/* -> 127.0.0.1:8000 (API-only Python artifact)

Approved operator network only
  -> separate internal nginx :443 + CIDR allow-list
       -> 127.0.0.1:8100 (authenticated run-history dashboard)

API-only service       -> TLS-verified, read-only brerc_api database login
Run-history service    -> TLS-verified, read-only brerc_monitor database login
Initial/refresh loader -> separate hardened one-shot units and loader login
```

Only nginx accepts HTTPS traffic. PostgreSQL/PostGIS remains private and must
not listen on a public interface. Host or network policy must permit each
service account to reach only its intended database endpoint. The run-history
dashboard is not a path on the public hostname: it has a separate internal
hostname, private-interface/firewall restriction, CIDR allow-list and its own
application login.

## Immutable release layout

Replace `REPLACE_WITH_APPROVED_ARTIFACT_ID` in every rendered file with the
reviewed release identifier (normally a protected-main commit plus a verified
artifact digest). Do not use `/opt/brerc-dashboard/current`, another symlink or
a branch checkout in a unit. The deployment owner creates this root-owned,
non-writable layout:

```text
/opt/brerc-dashboard/releases/REPLACE_WITH_APPROVED_ARTIFACT_ID/
  bin/brerc-load               loader entry point in its reviewed runtime
  deploy/initial/              source of the separately installed approval helper
                               and first-load procedure; never execute the
                               root helper from the release tree
  deploy/refresh/              guarded full-snapshot refresh procedure
  deploy/validation/           success/failure evidence verifiers and fixed SQL
  web/dist/                    built React artifact
  api-runtime/                 API-only artifact
    app/                       api/app only
    venv/                      pinned API dependencies and uvicorn
  run-dashboard-runtime/       separately built internal viewer artifact
    app.py
    store.py
    static/
    venv/                      pinned run-dashboard dependencies and uvicorn
```

The public API runtime must be built from `api/app/` and the pinned API
dependency set only. It must not contain or import `etl`, `brerc_loader`,
`brerc_source`, migrations, source data, tests or the repository root. The
existing `api/Dockerfile` and `api/package_tests/test_api_only_package.py`
document and test this boundary even when the host uses a Python virtual
environment instead of a container. The run-history runtime is a different
artifact and Unix account; never merge it into the public API runtime.

Record the source commit, the SHA-256 of every artifact (including the
standalone root approval helper copied to
`/usr/local/libexec/brerc/consume-initial-approval.py`), the installed unit
and nginx configuration digests, and the dependency lock evidence. Follow
`deploy/initial/README.md` to install and audit that helper as root-owned,
non-writable code before an initial attempt; the unit must invoke that fixed
copy through its reviewed empty-environment pre-start command, never execute
root code from the application release tree. Directories and files under the
immutable release must be owned by the deployment owner and not writable by
`brerc-api`, `brerc-monitor-ui` or `brerc-loader`.

## Build and approve the release artifacts

Build only from the exact protected-main commit after its required CI has
passed. A dirty checkout, branch-only commit or unresolved dependency change
fails this gate. On a trusted Linux builder matching the target architecture,
the frontend build gate is:

```sh
cd web
npm ci
npm run audit:prod
npm run typecheck
npm run lint
npm run guard
npm run test:run
VITE_API_BASE_URL=/api npm run build
npm run guard:bundle
```

Do not set `VITE_USE_REAL_API` or `VITE_A11Y_TEST_MODE` for the production
build. The current source build requests CARTO Voyager tiles from
`https://basemaps.cartocdn.com`; this is code, not an operator-selectable
environment setting. If BRERC instead approves a self-hosted basemap or no
basemap, implement that as a reviewed frontend change and, for self-hosted
tiles, a reviewed serving/proxy change; then repeat every build, privacy, CSP
and browser gate before creating the artifact. Do not try to change the
provider only in nginx. Record the approved origin without credentials, or
record `NONE` for an approved no-basemap build. Copy only `web/dist/` into the
immutable web artifact; never deploy Vite's development or preview server.

The public nginx example deliberately contains the unresolved
`REPLACE_WITH_APPROVED_BASEMAP_ORIGIN` CSP token. Resolve it only after the
CARTO/self-hosted/no-basemap decision is approved: use the one exact HTTPS
origin when a third-party basemap is approved, or `'self'` when all basemap
resources are served by the public dashboard origin. Do not replace it
with `https:`, `*` or a wildcard. The origin is permitted only by `img-src` and
`connect-src`; every other resource remains same-origin (apart from the fixed
`data:`/`blob:` allowances needed by the built UI). If the approved decision is
to ship without a basemap, remove the token and prove the build makes no
basemap request. An unresolved token, an origin that differs from the approved
decision, or a browser CSP violation fails the release gate.

Build the API runtime from `api/app/` plus the exact `api` dependency set in
`api/pyproject.toml`; build the loader independently from the reviewed combined
package; and build the viewer only from `run-dashboard/app.py`, `store.py`,
`static/` and its pinned requirements. Run the API-only package test and refuse
an API artifact containing `etl`, `brerc_loader`, `brerc_source`, migrations,
tests or source data. Retain dependency inventories and digest the completed
artifacts. A later rebuild, even from the same commit, is a new artifact that
requires new review and evidence.

Stage the three runtimes under a new artifact-ID directory, verify every file
is root/deployment-owner controlled, then make the tree non-writable by all
service accounts. Never copy a repository checkout into an API or viewer
runtime and never mutate an approved release directory in place.

## Host inputs and permissions

Create system accounts with no interactive shell:

- `brerc-api` runs only the public API;
- `brerc-monitor-ui` runs only the private run-history viewer;
- `brerc-loader` remains exclusive to the initial/refresh units; and
- nginx retains its distribution-provided unprivileged worker account.

Create `/etc/brerc/production` as `root:root` mode `0755`. Create its `api` and
`monitor` children as `root:brerc-api` and `root:brerc-monitor-ui`, respectively,
both mode `0750`; the two service accounts must not belong to each other's
group. Render each tracked credential-free environment example into the matching
child as `root:root` mode `0644`. Supply the following files out of band from
BRERC's approved secret/configuration manager; never put their values in Git,
tickets, screenshots, shell history or acceptance output:

- `/etc/brerc/production/api/api.pgpass`, owned by `brerc-api:brerc-api` mode
  `0600`, containing only the API login's database password; the API libpq
  service file and trusted PostgreSQL CA remain `root:brerc-api` mode `0440`;
- `/etc/brerc/production/monitor/run-dashboard.secrets.env`, `root:root` mode
  `0400` and containing
  `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` and `DASHBOARD_SECRET_KEY`;
- `/etc/brerc/production/monitor/monitor.pgpass`, owned by
  `brerc-monitor-ui:brerc-monitor-ui` mode `0600`, containing only the monitor
  login's database password; the monitor libpq service file and trusted
  PostgreSQL CA remain `root:brerc-monitor-ui` mode `0440`; and
- the public/internal TLS private keys, readable by nginx only.

Both web services use libpq service mode, so tracked environments contain
neither a password nor a complete connection string. Each service profile must
name only its dedicated login and database, contain no password, and is
overridden by the application's explicit `sslmode=verify-full`, CA and passfile
settings. The API must never use the loader, monitor, Martin, database-owner or
superuser role. Do not set `DATABASE_URL` or `PGPASSWORD` for either service.
`APP_ENV=prod` and `DASHBOARD_ENV=prod` are fixed in their reviewed units and
must not be repeated in either environment file, because systemd environment
files override `Environment=` values. The monitor environment must also omit
`RUN_DASHBOARD_DATABASE_URL`; production uses only the reviewed service profile.
Render `api-pg-service.conf.example` and `monitor-pg-service.conf.example` into
the two paths above. Reject any rendered profile containing `password=`, an IP
address in place of the certificate's approved database hostname, or another
login/database. Each passfile must have no group/world permissions (mode
`0600`); libpq ignores insecure password files on Unix. Do not make a
root-owned `0600` passfile that the unprivileged service account cannot read.

Before either web service starts, run the catalogue-only audit from the
destination database owner session. Use controlled deployment variables for
the three names; no password belongs on this command line:

```sh
psql -X --set=ON_ERROR_STOP=1 \
  --dbname=REPLACE_WITH_PUBLICATION_DATABASE_NAME \
  --set=expected_database=REPLACE_WITH_PUBLICATION_DATABASE_NAME \
  --set=api_login=REPLACE_WITH_API_LOGIN_ROLE \
  --set=monitor_login=REPLACE_WITH_MONITOR_LOGIN_ROLE \
  --file=deploy/validation/audit_runtime_logins.sql
```

The audit fails if either login has unsafe attributes, extra effective role
membership, membership administration, disabled membership inheritance,
direct/default object grants or owns an object. Retain its fixed pass/fail
output; do not retain a connection string.

## Render and validate on the target Linux host

Work in a root-only staging directory. Replace every placeholder, but keep the
immutable release path identical in the two web-service units, the loader units
and public nginx file. Before installing anything:

1. Verify the protected-main commit, artifact digests, root ownership and lack
   of service-account write access. Verify that the API-only artifact cannot
   import any write-capable repository package.
2. Copy the two web-service unit examples to temporary names ending in
   `.service`. Independently stage both initial units and all four refresh
   units as their runbooks require. Run `systemd-analyze verify` against all
   eight rendered units together on the target host's systemd version; this
   must resolve every `OnFailure`, guard and timer dependency. Treat every
   unknown or ignored directive as a failed gate. Audit the fixed root helper
   using `namei -l` and its approved digest, as required by the initial
   runbook; systemd syntax checking alone cannot establish its provenance.
3. Review `systemd-analyze security` for all seven rendered services on that host.
   Record the report and every approved exception; do not weaken a directive
   merely to improve the score or silence a compatibility error.
4. Copy the nginx examples to temporary names ending in `.conf`, render the
   hostnames/private IP/operator CIDR/certificate paths and the approved exact
   basemap CSP origin, then run `nginx -t` against the complete candidate
   configuration. Confirm no placeholder remains and the public and internal
   server blocks do not overlap.
5. Verify with `ss -lntp` and firewall rules that ports 8000 and 8100 are
   loopback-only, PostgreSQL is private, only public nginx is Internet-facing,
   and the internal hostname is reachable solely from the approved operator
   network.

The exact commands depend on BRERC's Linux distribution and staging paths. A
reviewer must retain the command output, host OS/systemd/nginx versions, hashes
and approval record without retaining secrets or private connection details.

## Install and controlled rehearsal

Only after the target-host review passes, copy the rendered API and viewer
units to `/etc/systemd/system/` and the two vhosts to the distribution's nginx
configuration directory as `root:root` mode `0644`. Install the separate
initial, initial-quarantine, refresh, refresh-quarantine, refresh-approval-guard
and refresh-timer units only by their respective reviewed runbooks; do not
enable either loader service or the timer as part of the web-service install.
Keep the public vhost dark or restricted to the approved review network until
the first publication and all release gates have passed. Then:

1. Run `systemctl daemon-reload`, `systemctl cat` for both web-service units and
   `nginx -t`.
   Compare the displayed files with the approved digests.
2. Start the API and run-history services without enabling them. Confirm their
   systemd invocation IDs, unprivileged users, immutable working directories
   and loopback listeners. Inspect only invocation-scoped journals.
3. Start/reload nginx with public access still blocked. From the approved
   review network, confirm the React application loads and `/api/health`
   succeeds through the same public origin and final HTTPS proxy. Confirm
   browser mocks are absent, the CSP header matches the approved basemap decision and the
   browser records no CSP violation while the static routes are exercised.
   Do not require a populated release endpoint yet: the first `initial` load
   has not occurred. Confirm
   `/maplibre-gl-worker.cjs` returns `200`, a JavaScript `Content-Type` and
   `X-Content-Type-Options: nosniff`; a missing or generic binary MIME type is a
   failed gate because Firefox cannot initialise the map worker safely.
4. Confirm the public hostname returns `404` for `/tiles`, `/tiles/anything`,
   `/run-dashboard` and `/run-dashboard/anything`; confirm port 8100 is not
   externally reachable.
5. From the approved operator network, confirm the internal hostname uses a
   trusted certificate, rejects a disallowed source address, presents the
   dashboard login, rejects invalid credentials and shows only bounded run
   history after a valid login.
6. With public access still blocked, perform the one-time real `initial` load
   only through the reviewed hardened unit and single-use approval process in
   `deploy/initial/README.md`. Retain its exact systemd invocation, database
   window, monitor-role query, API and mocks-off browser evidence. An absent
   marker or zero-job failure is not permission to retry; use the runbook's
   quarantine and failed-attempt procedure.
7. From the approved review network, now exercise every public route and the
   map through the final proxy. Require the database evidence, both API
   identity endpoints and browser to agree on the active `releaseId` and
   `datasetVersion`. Do not open the public vhost because a static health check
   alone passed.
8. Perform attended changed, no-change and deliberate-failure complete-snapshot
   `refresh` rehearsals exactly as `deploy/refresh/README.md` specifies. Its
   root-owned approval guard and volatile `/run/brerc/refresh/APPROVED_TO_SCHEDULE`
   marker govern the timer; `Persistent=false` prevents missed-run catch-up.
   Do not enable recurring refresh until every invocation's evidence, the
   schedule, dead-man monitor and failure route are accepted. A failed run
   must leave the previous active release visible and the marker absent.
9. Reboot once in the controlled window. Require the approval marker to remain
   absent, inspect and stop any active refresh timer, then repeat the listener,
   API, authentication and release-identity checks. Revalidate the host and
   obtain explicit operator approval before re-arming the schedule; reboot is
   not an implicit renewal. Test the soft-reboot/sleep disarm behavior if those
   transitions are permitted on the host.

After the retained evidence is accepted, enable the two long-running units with
`systemctl enable --now brerc-public-api.service brerc-run-dashboard.service`,
reload nginx through the distribution's normal service, and repeat the public
and private health checks. Enabling these services does not enable the loader
timer; that remains the separate approval in `deploy/refresh/README.md`.

The actual hardened units—not an interactive shell, development server or root
Compose stack—must be used for the accepted rehearsal.

Record the outcome with
`deploy/validation/TARGET_LINUX_ACCEPTANCE_RECORD.md.example` in BRERC's
restricted evidence store. Do not commit the completed record if it contains
private operational metadata.

## Failure recovery and rollback

- If a service fails before nginx changes, keep the previous application
  release running. Preserve its invocation-scoped journal, correct the new
  immutable artifact/configuration through review and repeat the rehearsal.
- If the new web/API/viewer release fails after cut-over, stop it and render new
  unit/nginx files that name the previous approved, digest-verified immutable
  artifact. Run `systemd-analyze verify`, `nginx -t`, daemon-reload/restart and
  every public/private smoke check again. Never repoint a mutable symlink.
- A failed `initial` must leave no active release; a failed `refresh` must leave
  the previous active release visible. Stop/disarm the timer and approval guard
  in the order specified by `deploy/refresh/README.md`, preserve the failed
  service state until invocation-scoped evidence is captured, and follow the
  initial/refresh recovery steps. Never repair a release pointer with manual
  SQL, run the legacy nightly job, use an obsolete schema or add a force flag.
- A successful but semantically wrong data release requires an approved
  corrected complete snapshot. Database-level reactivation is a BRERC DBA
  incident action requiring its own reviewed runbook; this package does not
  authorise it.
- Keep the public site unavailable rather than falling back to mock data,
  individual coordinates, a write-capable API role or an unverified database.

After recovery, reconcile the active release identity through the database,
public API and mocks-disabled browser before enabling services or the refresh
timer. Record who authorised the rollback, both artifact digests, timestamps
and final health without recording credentials, DSNs, raw records or precise
locations.

## Acceptance boundary

The examples and static tests can be completed by the delivery team. Production
acceptance is not true until BRERC's named operator runs the rendered files on
the target Linux host, records the compatibility/security outputs, performs the
controlled hardened-unit rehearsal and signs the resulting evidence. Any
unresolved placeholder, public run-history route, public database listener,
API artifact containing ETL code, failed identity reconciliation or missing
rollback proof blocks activation.
