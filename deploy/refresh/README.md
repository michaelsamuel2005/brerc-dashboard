# Hardened full-snapshot refresh scheduler

## Status and safety boundary

This directory is a deployment package, not an enabled deployment. Both unit
files end in `.example`; the repository and CI neither install nor enable them.
The additional `APPROVED_TO_SCHEDULE` condition keeps an accidentally copied
service inert until an authorised operator deliberately creates the marker.

The service has exactly one operational command:

```text
/opt/brerc-dashboard/current/bin/brerc-load refresh --config /etc/brerc/refresh/loader.configuration.yaml
```

It performs the privacy-gated, atomic **full-snapshot refresh**. It does not run
the legacy `nightly_job`, initial mode, incremental mode, ad-hoc SQL or a shell
wrapper. A failed candidate must leave the previous `serve.*` release active.

The templates do not choose production policy. Before installation, the
authorised service owner must record approval for all of the following:

- production host and accountable operator;
- exact cadence, UTC maintenance window and `Persistent=true` catch-up action;
- outer timeout, justified by a retained scale run from the exact protected-main
  release candidate;
- full-snapshot row-count and publication-basis change thresholds;
- source view identity, destination identity, TLS endpoints and CA ownership;
- secret-store/export mechanism and rotation ownership; and
- notification transport, recipients, escalation window and independent
  missed-run/dead-man monitor owner.

An example time, hostname, address or recipient in this package is not an
approval. Do not install the timer until those decisions are signed off.

## Required external inputs

Install the reviewed application release read-only beneath
`/opt/brerc-dashboard`, exposing the approved version as
`/opt/brerc-dashboard/current`. Build it from an exact protected-main commit and
record the commit and immutable wheel/container digest. Do not resolve new
packages from the Internet during the production install.

Create a dedicated system account with no login shell and no home directory:

```sh
sudo useradd --system --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin brerc-loader
sudo install -d -o root -g brerc-loader -m 0750 /etc/brerc/refresh
```

Prepare these files outside the repository:

| Path | Purpose | Recommended ownership/mode |
| --- | --- | --- |
| `/etc/brerc/refresh/loader.configuration.yaml` | Loader config copied from `api/loader.configuration.example.yaml`, with all approved digests, destination identity and refresh thresholds | `root:brerc-loader`, `0440` |
| `/etc/brerc/refresh/source.configuration.yaml` | Source contract copied from `api/configuration.example.yaml`, with the approved view and role identity | `root:brerc-loader`, `0440` |
| `/etc/brerc/refresh/publication-policy.approved.json` | Exact approved publication evidence named by the loader config | `root:brerc-loader`, `0440` |
| `/etc/brerc/refresh/species-dictionary.approved.csv` | Exact approved dictionary named by the loader config | `root:brerc-loader`, `0440` |
| `/etc/brerc/refresh/loader-runtime.env` | Secret-store export based on `loader-runtime.env.example` (read by systemd before it changes user) | `root:root`, `0600` |
| `/etc/brerc/refresh/pg_service.conf` | libpq file containing distinct named source and target services | `root:brerc-loader`, `0440` |
| `/etc/brerc/refresh/source.pgpass` and `target.pgpass` | Separate database credentials | `brerc-loader:brerc-loader`, `0600` |
| `/etc/brerc/refresh/source-ca.pem` and `target-ca.pem` | Approved TLS trust roots | `root:brerc-loader`, `0440` |

Change `source_config_path`, dictionary path and policy path in the copied loader
configuration to `/etc/brerc/refresh/...`. Replace every placeholder and hash
with the reviewed value. `PGPASSWORD`, DSNs, inline passwords and `sslmode`
weaker than `verify-full` are prohibited and are rejected by the loader. Never
put a secret, raw SQL, record, coordinate or internal connection string in Git,
a ticket, shell history, screenshots or the evidence bundle.

Both connectors intentionally bind the same process-global `PGSERVICEFILE`.
Consequently, `pg_service.conf` must contain two separately named profiles,
selected by `BRERC_SOURCE_SERVICE` and `BRERC_TARGET_SERVICE`; do not configure
two service-file paths. The two passfiles and CA files remain separate. The two
HMAC secrets must also be distinct, stable values of at least 32 UTF-8 bytes.
Rotating either changes reconciliation identity, and rotating the public-ID key
also changes published identifiers, so rotation requires an approved migration
and recovery plan rather than an unattended secret update.

## Preflight and first controlled refresh

Complete these checks before creating `APPROVED_TO_SCHEDULE`:

1. Verify the release commit and artifact digest against the approved release
   record. Confirm `/opt/brerc-dashboard/current/bin/brerc-load` is owned by the
   deployment owner, is not writable by `brerc-loader`, and resolves to that
   exact release.
2. Verify the destination migration is current and that its database,
   environment UUID and loader role equal the three pinned values in
   `loader.configuration.yaml`. Verify the source view version, 39-column
   contract and read-only role against the approved source evidence.
3. Independently calculate SHA-256 for the policy and dictionary bytes and
   compare them with the loader config. Review every refresh limit; placeholders
   or inferred initial-load limits are not acceptable.
4. Check all ownership/modes in the table. Confirm the source role cannot write,
   the target loader role cannot bypass the publication boundary, both named
   services resolve to the intended hosts, and both certificates validate their
   hostnames. Do not print the environment or connection parameters.
5. Confirm the previous active release ID and a privacy-safe baseline of its
   structural counts. Confirm the database-backed monitoring/outbox migration is
   present. Configure an independent scheduler-failure/dead-man check: database
   outbox rows cannot report a failure that occurs before the loader connects.
   Confirm journald retention and access controls preserve useful exit evidence
   without granting dashboard users or notification workers broad journal access.
6. Copy the examples to temporary names ending `.service` and `.timer` in a
   protected staging directory and run `systemd-analyze verify` against both.
   Review `systemd-analyze security` on the actual production systemd version;
   do not delete a hardening directive merely to improve compatibility without
   a documented security review.
7. Arrange the approved maintenance window and observer. Then run one controlled
   `brerc-load refresh` with precisely the service user, environment file and
   config that the unit will use. This is a real candidate publication attempt,
   not a dry run. Do not schedule anything until its evidence is accepted.

For step 7, use a transient one-shot unit or install the service unit without
the timer, create the approval marker for the observed run, start the service
once, then remove the marker immediately. Never source the environment file into
an interactive shell. Inspect status with `systemctl status` and
`journalctl -u brerc-loader-refresh.service`; export only redacted evidence.

## Acceptance evidence

Retain the following together under the organisation's access-controlled
evidence policy:

- protected-main commit, immutable application digest, unit-file digest and
  production systemd version;
- digests (not contents) of the loader config, source config, policy and species
  dictionary, plus the approval record governing them;
- approved UTC window, start/end times and configured timeout;
- redacted job ID, candidate/previous/final active release IDs, source snapshot
  time, structural row/species/cell/year counts and candidate digest;
- terminal success/failure state and proof that failure retained the previous
  active release;
- public API `releaseId`/`datasetVersion` coherence and a real dashboard smoke
  check with browser mocks disabled; and
- notification delivery acknowledgement plus the independent missed-run check.

Do not retain raw records, person data, coordinates, credentials, DSNs, private
hosts, source SQL or unredacted exception text in this bundle. The loader writes
database run history and a privacy-safe notification outbox, but this scheduler
does not deliver messages. A separately reviewed worker must drain that outbox.
Recipients and escalation routes remain an operator approval, not a code default.

## Install and activate only after acceptance

After all approvals and the controlled refresh have passed, copy the examples
to `/etc/systemd/system/brerc-loader-refresh.service` and
`/etc/systemd/system/brerc-loader-refresh.timer`, preserving `root:root` and
mode `0644`. Put the approved `OnCalendar` value in the installed timer. Create
`/etc/brerc/refresh/APPROVED_TO_SCHEDULE` as `root:brerc-loader` mode `0440`, run
`systemctl daemon-reload`, then `systemctl enable --now
brerc-loader-refresh.timer`. Verify `systemctl list-timers` shows the approved
next run in UTC and ensure the dead-man monitor expects that same window.

`Persistent=true` asks systemd to catch up a missed run after downtime. If BRERC
does not approve immediate catch-up, change that setting before installation;
do not silently inherit the example.

## Failure and rollback

1. Stop and disable `brerc-loader-refresh.timer`, then remove the approval marker
   so no further refresh can begin. Preserve the journal and database evidence.
2. If a refresh failed, verify the previous release is still active through the
   API identity and safe structural counts. Do not move a `serve.*` pointer with
   manual SQL, run the legacy nightly path, use a force flag or edit a manifest.
3. Correct the source, configuration, policy or release artifact through review.
   Re-run only `brerc-load refresh` in a new approved window; atomic activation
   is the recovery mechanism.
4. If application code itself must be rolled back, repoint
   `/opt/brerc-dashboard/current` only to a previously approved, digest-verified
   build that is compatible with the installed database migration. Reload the
   unit and repeat the API/dashboard smoke tests before re-enabling the timer.
5. A successful but semantically wrong data release requires an approved
   corrected full snapshot. Emergency database-level reactivation of an older
   release is a DBA incident action and needs its own reviewed runbook; it is not
   authorised by these templates.

Removing the timer later does not authorise deleting configuration, credentials,
logs or evidence. Their retention and secure destruction remain with the named
service and data owners.
