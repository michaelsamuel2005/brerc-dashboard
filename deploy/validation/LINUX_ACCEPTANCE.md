# Target Linux compatibility and controlled production rehearsal

This is the acceptance record for the **rendered, installed production units**.
Repository unit examples and GitHub CI prove the team-owned contract; they do
not prove compatibility with BRERC's chosen Linux host, firewall, certificate
store or private network. BRERC's operator runs this procedure with a team
observer before public activation and retains the completed record privately.
Use `TARGET_LINUX_ACCEPTANCE_RECORD.md.example` as the controlled sign-off
template. A blank or `TBD` gate is a failed gate, not provisional approval.

The root `docker-compose.yml`, root `Caddyfile`, Vite preview server, legacy
schema, legacy `nightly_job` and any Martin placeholder are excluded. They are
not fallback production methods.

Repository changes are gated by the cross-platform contract tests and, on
GitHub's Ubuntu runner, systemd's own offline parser:

```sh
python deploy/validation/verify_systemd_examples.py
python deploy/validation/verify_systemd_examples.py --systemd-analyze
```

Those checks cover all six public-API, private-monitor, initial-load, refresh,
quarantine and timer examples. They reject mutable release paths, unsafe
listeners, missing failure quarantine and weakened sandboxing. They validate
examples only; they do not install, start or accept a service and therefore do
not replace any target-host step below.

## Acceptance identity

Record without secrets or private endpoint values:

- protected-main commit and immutable artifact identifier/digest;
- Linux distribution/kernel and `systemd --version` output;
- host asset/CMDB identifier, operator, observer and UTC window;
- SHA-256 of every installed unit, environment/config file, policy and species
  dictionary (digests only for secret or controlled files);
- approved public and private hostname certificate fingerprints;
- database migration history `0001` through `0004` and destination environment
  UUID through the restricted operational channel; and
- the approval record authorising this rehearsal.

## 1. Offline unit and artifact validation

Render every `REPLACE_WITH_APPROVED_ARTIFACT_ID` token to one immutable
`/opt/brerc-dashboard/releases/<id>` directory. Reject any unresolved token,
path through `current`, symlinked executable or group/world-writable code.
Render `REPLACE_WITH_APPROVED_BASEMAP_ORIGIN` to the exact HTTPS origin from the
approved CARTO/self-hosted decision (`'self'` for same-origin resources). Reject
`https:`, `*`, wildcards, an unapproved origin or an unresolved token. The
origin may appear only in the CSP's `img-src` and `connect-src` directives.
The current frontend source uses CARTO Voyager directly. A self-hosted or
no-basemap decision therefore requires a reviewed frontend commit and a new
artifact; changing only this CSP token is not an implementation of that
decision.

Before installation, and again against the installed files, run:

```sh
sudo systemd-analyze verify \
  /etc/systemd/system/brerc-public-api.service \
  /etc/systemd/system/brerc-run-dashboard.service \
  /etc/systemd/system/brerc-loader-initial.service \
  /etc/systemd/system/brerc-loader-refresh.service \
  /etc/systemd/system/brerc-loader-refresh-quarantine.service \
  /etc/systemd/system/brerc-loader-refresh.timer
sudo systemd-analyze security brerc-public-api.service
sudo systemd-analyze security brerc-run-dashboard.service
sudo systemd-analyze security brerc-loader-initial.service
sudo systemd-analyze security brerc-loader-refresh.service
sudo systemd-analyze security brerc-loader-refresh-quarantine.service
sudo systemctl cat brerc-public-api.service brerc-run-dashboard.service \
  brerc-loader-initial.service brerc-loader-refresh.service \
  brerc-loader-refresh-quarantine.service brerc-loader-refresh.timer
sudo systemctl show brerc-public-api.service brerc-run-dashboard.service \
  brerc-loader-initial.service brerc-loader-refresh.service \
  --property=FragmentPath --property=DropInPaths --property=User \
  --property=Group --property=ExecStart --property=EnvironmentFiles
sudo systemd-delta
```

Any unknown/ignored directive, unexpected drop-in, wrong user, mutable path or
security regression fails acceptance. Do not delete hardening merely to make an
older host accept the file; document, review and test an equivalent control or
upgrade the host. Retain command output in the restricted evidence bundle.
Inspect the rendered credential-free environment files as root and confirm they
do not assign `APP_ENV` or `DASHBOARD_ENV`; those modes are fixed to `prod` in
the units and an environment-file assignment would override the fixed value.
Also confirm the monitor environment does not assign
`RUN_DASHBOARD_DATABASE_URL` and neither service receives `PGPASSWORD`.

## 2. Network, TLS and privilege boundary

Prove all of the following from an authorised test point:

- only the reverse proxy's approved HTTPS listeners are externally reachable;
- FastAPI listens only on `127.0.0.1:8000` and the run-history dashboard only
  on `127.0.0.1:8100`;
- the run-history hostname is unreachable from the public Internet and requires
  BRERC's approved VPN/SSO or equivalent access control;
- PostgreSQL/PostGIS is private and its firewall/`pg_hba.conf` allow only the
  dedicated source, loader, API and monitor paths that need it;
- source and target database sessions use `verify-full` with the approved CA,
  hostname and least-privilege role;
- `deploy/validation/audit_runtime_logins.sql` passes in the exact destination
  database for the deployed API and monitor login names, proving their role
  attributes, sole effective membership, lack of object ownership and lack of
  direct/default object grants;
- wrong CA, hostname, database, environment UUID or role fails before work;
- the loader has no inbound listener and egress is restricted to the approved
  source/target endpoints by BRERC's host/network controls; and
- the public virtual host returns 404 for `/tiles`, the private dashboard and
  operational paths, while `/api/*` is same-origin and never cached.

Do not put addresses, credentials, certificate private keys or command output
containing them in public CI artifacts or ordinary tickets.

## 3. Dark first-load rehearsal through the hardened unit

Keep public traffic disabled. Follow `deploy/initial/README.md` exactly, using
the installed hardened unit—not a shell invocation of `brerc-load`. Observe one
and only one attempt. Require:

- the root-owned approval marker is consumed before either database is opened;
- a second start without a new approval fails;
- systemd terminates successfully with one invocation-scoped loader result;
- loader `runId`/`releaseId`/candidate digest, migration-0004 evidence and both
  API identity endpoints reconcile with `verify_release_evidence.py`;
- a browser smoke test uses the production proxy/build with mocks disabled;
- no source row, coordinate, person data or credential enters the evidence; and
- the initial unit remains disabled and has no timer or automatic retry.

A deliberate rejected-input rehearsal must leave no active release and the
approval marker absent. A new attempt requires a new approval.

## 4. Complete-snapshot refresh and rollback rehearsal

With the initial release still dark:

1. Run one approved **changed** complete-snapshot refresh through
   `brerc-loader-refresh.service`. Confirm one atomic release switch and exact
   database/API/browser identity agreement.
2. Run one approved **no-change** refresh. Require
   `reusedActiveRelease:true`, unchanged release identity and an advanced
   checked-through source time.
3. Run one deliberate failing refresh (for example, a reviewed wrong-CA test).
   Confirm the previous release and safe counts remain visible, the quarantine
   service removes `APPROVED_TO_SCHEDULE`, the timer cannot start more work and
   the independent alert/dead-man path reports the failure.
4. Correct the cause, obtain a new approval, perform one attended refresh and
   only then re-arm the timer. Never move `serve.*` with manual SQL.
5. Rehearse **code/proxy rollback** to a prior immutable, digest-verified build
   known to be compatible with the installed forward-only migrations. Confirm
   the active database release is not changed by a code rollback.

If a successfully published release is later judged unsafe, withdraw public
traffic, disable/disarm refresh, preserve evidence and publish only a newly
approved corrected full snapshot. Database restore or old-release reactivation
is a separate DBA incident procedure, not an application rollback command.

## 5. Serving and private-monitor checks

Through the approved public hostname, verify the built React application,
client-side route reloads, `/api/health`, `/api/summary` and
`/api/meta/provenance`. Run the mocks-disabled browser acceptance suite against
that hostname. Confirm `index.html` is revalidated, fingerprinted assets are
immutable-cacheable, API responses are `no-store`, and the approved security
headers/CSP are present. Exercise every route and the map with browser developer
tools or an equivalent automated listener, retain a zero-violation CSP report,
and prove the basemap request origin exactly matches the approved decision.

Through the private operator path, verify the run-history dashboard sees the
same PostgreSQL-backed jobs and refreshes from running to terminal state. Prove
that its login cannot read public base tables, source records, credentials or
journald and that the public hostname cannot route to it.

## 6. Sign-off and activation decision

Acceptance passes only when every item above has retained evidence and these
roles sign the exact artifact and host result:

- BRERC service owner/operator;
- BRERC database/network owner;
- team technical reviewer; and
- accessibility/content approver for the public activation build.

Record `PASS` or `FAIL`, UTC time, artifact digest and evidence-bundle location.
Do not record credentials or private data. A failure leaves public traffic off,
the initial marker absent and the refresh schedule disabled/disarmed.
