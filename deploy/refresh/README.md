# Hardened full-snapshot refresh scheduler

## Status and safety boundary

This directory is a deployment package, not an enabled deployment. All three
unit templates end in `.example`.
The repository and CI neither install nor enable them.
The additional `APPROVED_TO_SCHEDULE` condition keeps an accidentally copied
service inert until an authorised operator deliberately creates the marker.
If an authorised refresh later fails, `OnFailure` starts the separate quarantine
unit, whose only command removes that marker as root. The installed timer may
continue to wake on its approved cadence, but the refresh condition then fails
closed and no further loader attempt can begin until an operator re-arms it.

The service has exactly one operational command:

```text
/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/bin/brerc-load refresh --config /etc/brerc/refresh/loader.configuration.yaml
```

It performs the privacy-gated, atomic **full-snapshot refresh**. It does not run
the legacy `nightly_job`, initial mode, incremental mode, ad-hoc SQL or a shell
wrapper. A failed candidate must leave the previous `serve.*` release active.
For the first production `initial` attempt, use the separate inert example and
operator gate in [`../initial/README.md`](../initial/README.md); the refresh
approval marker does not authorise that first load.

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
`/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID`. The identifier must bind
the exact protected-main commit and immutable wheel/container digest. Render
that exact nonsymlink path into the installed unit in place of
`REPLACE_WITH_APPROVED_ARTIFACT_ID`; never execute the loader through `current`
or another mutable symlink. Do not resolve new packages from the Internet
during the production install.

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
   record. Confirm the rendered immutable release path and its `bin/brerc-load`
   are owned by the deployment owner, are not writable by `brerc-loader`, and
   exactly match that release. Reject an unresolved placeholder or any symlink.
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
6. Copy the three examples to temporary names ending `.service` and `.timer` in
   a protected staging directory and run `systemd-analyze verify` against all
   three, including the exact `OnFailure` relationship.
   Review `systemd-analyze security` on the actual production systemd version;
   do not delete a hardening directive merely to improve compatibility without
   a documented security review.
7. Arrange the approved maintenance window and observer. Then run one controlled
   `brerc-load refresh` with precisely the service user, environment file and
   config that the unit will use. This is a real candidate publication attempt,
   not a dry run. Do not schedule anything until its evidence is accepted.

For step 7, install the rendered service and quarantine units without the timer,
create the approval marker for the observed run, record the previous
`InvocationID`, and start the service once with `systemctl start --no-block`.
Never source the environment file into an interactive shell. Wait until the
unit reaches a terminal state, then remove the schedule marker after confirming
that no further attempt is running. A failed run must already have caused the
quarantine unit to remove it.

Capture evidence for this invocation only. Replace
`CONTROLLED_EVIDENCE_DIRECTORY`, `APPROVED_MONITOR_SERVICE` and the public host
with protected deployment values; none belongs in Git or shell screenshots:

```sh
unit=brerc-loader-refresh.service
invocation_id="$(systemctl show "$unit" --property=InvocationID --value)"
case "$invocation_id" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo 'invalid InvocationID' >&2; exit 1 ;;
esac
evidence=CONTROLLED_EVIDENCE_DIRECTORY
systemctl show "$unit" \
  --property=InvocationID --property=Result --property=ExecMainCode \
  --property=ExecMainStatus --property=ActiveState --property=SubState \
  > "$evidence/unit.properties"
journalctl _SYSTEMD_INVOCATION_ID="$invocation_id" --output=json \
  > "$evidence/journal.json"
run_id="$(jq -ers --arg id "$invocation_id" '
  [.[] | select(._SYSTEMD_INVOCATION_ID == $id) |
   (.MESSAGE | fromjson?) |
   select(.status == "ok" and .state == "succeeded" and .mode == "refresh")]
  | if length == 1 then .[0].runId else error("not exactly one result") end
' "$evidence/journal.json")"
psql APPROVED_MONITOR_SERVICE --tuples-only --no-align \
  --set=run_id="$run_id" \
  --file=/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/release_evidence_query.sql \
  > "$evidence/database.json"
curl --fail --silent --show-error https://APPROVED_PUBLIC_HOST/api/summary \
  > "$evidence/api-summary.json"
curl --fail --silent --show-error https://APPROVED_PUBLIC_HOST/api/meta/provenance \
  > "$evidence/api-provenance.json"
python3 /opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/verify_release_evidence.py \
  --invocation-id "$invocation_id" --mode refresh \
  --unit-properties "$evidence/unit.properties" \
  --journal-json "$evidence/journal.json" \
  --database-json "$evidence/database.json" \
  --api-summary-json "$evidence/api-summary.json" \
  --api-provenance-json "$evidence/api-provenance.json"
```

Confirm the invocation ID is non-empty and differs from the recorded previous
ID. `journalctl -u` is useful for diagnosis but is not acceptance evidence
because it mixes attempts. The verifier supports both a changed refresh and a
validated no-change refresh; in the latter, `reusedActiveRelease` must be true
and the result/base/API release IDs must remain equal.

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
to `/etc/systemd/system/brerc-loader-refresh.service`,
`/etc/systemd/system/brerc-loader-refresh-quarantine.service` and
`/etc/systemd/system/brerc-loader-refresh.timer`, preserving `root:root` and
mode `0644`. Put the approved `OnCalendar` value in the installed timer. Create
`/etc/brerc/refresh/APPROVED_TO_SCHEDULE` as `root:brerc-loader` mode `0440`, run
`systemctl daemon-reload`, then verify that `systemctl cat
brerc-loader-refresh.service` contains the exact reviewed `OnFailure` target.
Enable the timer with `systemctl enable --now brerc-loader-refresh.timer`.
Verify `systemctl list-timers` shows the approved next run in UTC and ensure the
dead-man monitor expects that same window. The quarantine unit is pulled in by
`OnFailure`; do not enable it independently.

`Persistent=true` asks systemd to catch up a missed run after downtime. If BRERC
does not approve immediate catch-up, change that setting before installation;
do not silently inherit the example.

## Failure and rollback

1. A failed `brerc-loader-refresh.service` must start
   `brerc-loader-refresh-quarantine.service`, which removes only
   `/etc/brerc/refresh/APPROVED_TO_SCHEDULE`. Verify both the quarantine unit's
   successful status and the marker's absence. If either check fails, stop and
   disable `brerc-loader-refresh.timer` and have an authorised root operator
   remove that exact marker. Preserve the invocation-scoped journal and database
   evidence. Never use a wildcard or remove any other file in the configuration
   directory.
2. Stop and disable the timer while the cause is investigated. Although a timer
   that remains enabled cannot pass the missing-marker condition, disabling it
   prevents a race while an operator deliberately re-arms the schedule.
3. If a refresh failed, verify the previous release is still active through the
   API identity and safe structural counts. Do not move a `serve.*` pointer with
   manual SQL, run the legacy nightly path, use a force flag or edit a manifest.
4. Correct the source, configuration, policy or release artifact through review.
   Re-run only `brerc-load refresh` in a new approved window; atomic activation
   is the recovery mechanism.
5. If application code itself must be rolled back, render and install a newly
   reviewed unit that names a previously approved, digest-verified immutable
   build compatible with the installed database migration. Never repoint a
   mutable runtime symlink. Reload the unit and repeat the API/dashboard smoke
   tests before re-enabling the timer.
6. A successful but semantically wrong data release requires an approved
   corrected full snapshot. Emergency database-level reactivation of an older
   release is a DBA incident action and needs its own reviewed runbook; it is not
   authorised by these templates.

Re-arming is a new production decision, not an automatic retry. After the fix
and evidence have been reviewed, keep the timer disabled, reset the failed
service state, create a new root-controlled `APPROVED_TO_SCHEDULE` marker, and
perform one attended refresh. Only after that refresh succeeds and its release
identity is reconciled may the operator re-enable the timer. Never configure
`Restart=` on the loader or quarantine units and never recreate the marker from
an `ExecStopPost`, notification worker or timer hook.

Removing the timer later does not authorise deleting configuration, credentials,
logs or evidence. Their retention and secure destruction remain with the named
service and data owners.
