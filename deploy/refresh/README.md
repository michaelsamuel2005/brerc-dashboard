# Hardened full-snapshot refresh scheduler

## Status and safety boundary

This directory is a deployment package, not an enabled deployment. All four
unit templates end in `.example`.
The repository and CI neither install nor enable them.
The additional `/run/brerc/refresh/APPROVED_TO_SCHEDULE` condition keeps an
accidentally copied service inert until an authorised operator deliberately
creates the marker. A kernel reboot removes `/run` state, but a systemd soft
reboot preserves `/run`, and suspend or hibernate preserves it too. Therefore
the timer is bound to a root-owned approval guard. Stopping that guard for
sleep, soft reboot or shutdown removes the exact marker and stops the timer.
The volatile marker is never restored automatically. An enabled timer may be
started again by `timers.target` after a soft reboot or ordinary boot, but it
remains inert without the marker. After any transition, an authorised operator
must inspect and stop that timer, revalidate the host and explicitly re-arm the
schedule and marker; merely seeing an active timer is not approval.
If an authorised refresh later fails, `OnFailure` starts the separate quarantine
unit, whose only command removes that marker as root. The installed timer may
continue to wake on its approved cadence, but the refresh condition then fails
closed and no further loader attempt can begin until an operator re-arms it.
The quarantine unit is inert; do not enable it independently.
All other runtime prerequisites use fixed, shell-free
`ExecStartPre=/usr/bin/test` checks: unlike systemd `Assert*` directives, a
failed pre-start command puts the service in the failed state and activates the
quarantine unit.

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
- exact cadence, UTC maintenance window and whether to depart from the safe
  `Persistent=false` no-catch-up default;
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

Evidence queries use a third, operator-only connection that is never placed in
the loader environment. Create `/etc/brerc/operator` as `root:root` mode `0700`
with a root-owned `pg_service.conf` (`0400`), `monitor.pgpass` (`0600`) and
approved monitor CA (`0444` or stricter). Its named profile must pin the
approved database, the dedicated LOGIN role whose sole direct/effective group
is `brerc_monitor`, `sslmode=verify-full`, `sslrootcert` and the absolute
`passfile`. The login must have read-only transactions by default and no
superuser, database/role creation, replication or RLS-bypass privilege. In the
protected root operator shell, set only the non-secret path:

```sh
export PGSERVICEFILE=/etc/brerc/operator/pg_service.conf
```

Replace `APPROVED_MONITOR_SERVICE` below with that profile name. Never reuse a
source, loader, API or Martin login for monitoring, and never export the monitor
password or copy the operator service file into `/etc/brerc/refresh`.

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

Complete these checks before creating the volatile schedule marker:

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
6. Copy the four examples to temporary names ending `.service` and `.timer` in
   a protected staging directory and run `systemd-analyze verify` against all
   four, including the exact `OnFailure` and timer-to-approval-guard
   relationships. Run `systemd-analyze security --threshold=40 --no-pager` on
   all three services on the actual
   production systemd version. The threshold is rendered as exposure 4.0; the
   reviewed Ubuntu 24.04 baseline scores 3.2 or better. Do not delete a hardening
   directive merely to improve compatibility without a documented security
   review.
7. Arrange the approved maintenance window and observer. Then run one controlled
   `brerc-load refresh` with precisely the service user, environment file and
   config that the unit will use. This is a real candidate publication attempt,
   not a dry run. Do not enable the recurring schedule until its evidence is
   accepted. The timer is started but not enabled for this observed attempt
   solely to hold its lifecycle guard and invocation properties; its next
   trigger must be outside the controlled evidence window.

For step 7, install the rendered loader, approval-guard, quarantine and timer
units, preserving `root:root` ownership and mode `0644`. Render the already
approved `OnCalendar` value into the timer. Before any controlled publication
attempt, run `systemctl daemon-reload`, capture `systemctl cat` and `systemctl
show --property=FragmentPath --property=DropInPaths` for all four installed
units, and compare their SHA-256 digests with the reviewed rendered artifacts.
Require the expected `/etc/systemd/system/` fragment paths, empty
`DropInPaths=`, no unresolved placeholder or mutable symlink, the exact
reviewed `OnFailure` target, and the exact timer dependency on the approval
guard. Re-run `systemd-analyze verify` on all four installed units and retain
`systemd-analyze security --threshold=40 --no-pager` output for all three
services. A score above 4.0, any override, unexpected drop-in, path mismatch or
digest mismatch blocks this controlled attempt.

Create `/run/brerc/refresh` while the approval marker is absent, then start the
timer. Starting it also starts the approval guard. Require the guard to be
`active (exited)`, the timer to be active, the marker to remain absent, and the
next scheduled trigger shown by `systemctl list-timers` to fall outside the
attended controlled-run window. This active timer reference also keeps the
completed refresh invocation properties available for evidence capture. If any
of those checks fails, stop the timer and guard and do not create the marker.

Only after those checks pass, create the approval marker for the observed run,
record the previous `InvocationID`, and capture a validated UTC
`database_window_start` from the database clock through the monitor service
before starting the unit. Run the attended blocks in one dedicated root Bash
shell with a new absolute evidence directory that does not already exist. An
existing directory or file, an unset value, or any failed command must stop
the shell. Do not resume a partial block, reuse evidence from an earlier
attempt or start a second loader to repair a failed capture; preserve the
partial bundle and reconcile the unit, database and API state.

```bash
set -euo pipefail
set -C  # Do not overwrite an existing evidence file.
unit=brerc-loader-refresh.service
guard=brerc-loader-refresh-approval-guard.service
quarantine=brerc-loader-refresh-quarantine.service
timer=brerc-loader-refresh.timer
evidence=CONTROLLED_EVIDENCE_DIRECTORY
expected_environment_id=APPROVED_DESTINATION_ENVIRONMENT_UUID
expected_database=APPROVED_DESTINATION_DATABASE_NAME
expected_monitor_role=APPROVED_MONITOR_LOGIN_ROLE
case "$evidence" in
  /*) ;;
  *) echo 'evidence directory must be an absolute path' >&2; exit 1 ;;
esac
umask 077
mkdir -m 0700 -- "$evidence"  # Existing directory/symlink is a hard stop.
chown root:root -- "$evidence"
install -d -o root -g root -m 0750 /run/brerc/refresh
rm -f -- /run/brerc/refresh/APPROVED_TO_SCHEDULE
systemctl start "$timer"
[ "$(systemctl is-active "$guard")" = active ] || exit 1
[ "$(systemctl show "$guard" --property=SubState --value)" = exited ] || exit 1
[ "$(systemctl is-active "$timer")" = active ] || exit 1
test ! -e /run/brerc/refresh/APPROVED_TO_SCHEDULE
systemctl list-timers "$timer" --all --no-pager
# An authorised operator must confirm that NEXT is outside this controlled run.
install -o root -g brerc-loader -m 0440 /dev/null \
  /run/brerc/refresh/APPROVED_TO_SCHEDULE
previous_invocation_id="$(
  systemctl show "$unit" --property=InvocationID --value
)"
previous_quarantine_invocation_id="$(
  systemctl show "$quarantine" --property=InvocationID --value
)"
database_window_start="$(
  psql -X -v ON_ERROR_STOP=1 \
    --dbname='service=APPROVED_MONITOR_SERVICE' \
    --tuples-only --no-align \
    --command="SELECT pg_catalog.to_char(
      pg_catalog.clock_timestamp() AT TIME ZONE 'UTC',
      'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'
    )"
)"
case "$database_window_start" in
  ????-??-??T??:??:??.??????Z) ;;
  *) echo 'invalid database start time' >&2; exit 1 ;;
esac
systemctl start --no-block "$unit"
while systemctl show "$unit" --property=Job --value | grep -q .; do
  sleep 2
done
loader_result="$(systemctl show "$unit" --property=Result --value)"
systemctl show --timestamp=unix "$unit" \
  --property=Result --property=ExecMainCode --property=ExecMainStatus \
  --property=ActiveState --property=SubState \
  --property=InactiveExitTimestamp --property=StateChangeTimestamp
database_window_end="$(
  psql -X -v ON_ERROR_STOP=1 \
    --dbname='service=APPROVED_MONITOR_SERVICE' \
    --tuples-only --no-align \
    --command="SELECT pg_catalog.to_char(
      pg_catalog.clock_timestamp() AT TIME ZONE 'UTC',
      'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'
    )"
)"
case "$database_window_end" in
  ????-??-??T??:??:??.??????Z) ;;
  *) echo 'invalid database end time' >&2; exit 1 ;;
esac
if [ "$loader_result" = success ]; then
  rm -f -- /run/brerc/refresh/APPROVED_TO_SCHEDULE
else
  for attempt in $(seq 1 30); do
    quarantine_invocation_id="$(
      systemctl show "$quarantine" --property=InvocationID --value
    )"
    if [ -n "$quarantine_invocation_id" ] \
       && [ "$quarantine_invocation_id" != "$previous_quarantine_invocation_id" ] \
       && ! systemctl show "$quarantine" --property=Job --value | grep -q .; then
      break
    fi
    sleep 1
  done
  [ -n "$quarantine_invocation_id" ] || exit 1
  [ "$quarantine_invocation_id" != "$previous_quarantine_invocation_id" ] || exit 1
  [ "$(systemctl show "$quarantine" --property=Result --value)" = success ] || exit 1
fi
test ! -e /run/brerc/refresh/APPROVED_TO_SCHEDULE
```

Never source the environment file into an interactive shell. The `Job` poll
waits for this exact oneshot to reach a terminal state without treating a
loader failure as permission to skip evidence capture. A successful attended
run removes the marker explicitly. A failed run waits for a new successful
quarantine invocation. In both cases marker absence is verified before evidence
is accepted; never reset or restart the loader before that check completes.

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
if [ "$invocation_id" = "$previous_invocation_id" ]; then
  echo 'InvocationID did not change' >&2
  exit 1
fi
systemctl show --timestamp=unix "$unit" \
  --property=InvocationID --property=Result --property=ExecMainCode \
  --property=ExecMainStatus --property=ActiveState --property=SubState \
  --property=InactiveExitTimestamp --property=StateChangeTimestamp \
  > "$evidence/unit.properties"
printf '{"invocationId":"%s","mode":"refresh","windowStart":"%s","windowEnd":"%s"}\n' \
  "$invocation_id" "$database_window_start" "$database_window_end" \
  > "$evidence/database-window.json"
journalctl _SYSTEMD_INVOCATION_ID="$invocation_id" --output=json \
  > "$evidence/journal.json"
run_id="$(jq -ers --arg id "$invocation_id" '
  [.[] | select(._SYSTEMD_INVOCATION_ID == $id) |
   (.MESSAGE | fromjson?) |
   select(.status == "ok" and .state == "succeeded" and .mode == "refresh")]
  | if length == 1 then .[0].runId else error("not exactly one result") end
' "$evidence/journal.json")"
psql -X -v ON_ERROR_STOP=1 \
  --dbname='service=APPROVED_MONITOR_SERVICE' \
  --tuples-only --no-align \
  --set=run_id="$run_id" \
  --set=expected_environment_id="$expected_environment_id" \
  --set=expected_database="$expected_database" \
  --set=expected_role="$expected_monitor_role" \
  --file=/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/release_evidence_query.sql \
  > "$evidence/database.json"
curl --fail --silent --show-error https://APPROVED_PUBLIC_HOST/api/summary \
  > "$evidence/api-summary.json"
curl --fail --silent --show-error https://APPROVED_PUBLIC_HOST/api/meta/provenance \
  > "$evidence/api-provenance.json"
python3 /opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/verify_release_evidence.py \
  --invocation-id "$invocation_id" --mode refresh \
  --expected-environment-id "$expected_environment_id" \
  --expected-database "$expected_database" \
  --expected-role "$expected_monitor_role" \
  --unit-properties "$evidence/unit.properties" \
  --journal-json "$evidence/journal.json" \
  --database-window-json "$evidence/database-window.json" \
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
`/etc/systemd/system/brerc-loader-refresh-approval-guard.service`,
`/etc/systemd/system/brerc-loader-refresh-quarantine.service` and
`/etc/systemd/system/brerc-loader-refresh.timer`, preserving `root:root` and
mode `0644`. Put the approved `OnCalendar` value in the installed timer, then run
`systemctl daemon-reload`, then capture `systemctl cat` and `systemctl show
--property=FragmentPath --property=DropInPaths` for all four units. Require the
installed paths, empty `DropInPaths=`, approved SHA-256 digests, no unresolved
placeholder or mutable symlink, the exact reviewed `OnFailure` target, and the
exact timer binding to the approval guard. Re-run `systemd-analyze verify` on
all installed units and retain `systemd-analyze security --threshold=40
--no-pager` output for all three services
on the target host. A score above 4.0, any override or unexpected drop-in blocks
activation. Recreate `/run/brerc/refresh` without its marker, then enable the
timer with `systemctl enable --now brerc-loader-refresh.timer`. Verify that the
approval guard is `active (exited)`, the timer is active, the marker is absent,
and `systemctl list-timers` shows the approved next run in UTC. Ensure the
dead-man monitor expects that same window. Only after those checks may the
authorised operator create the marker with the ownership/mode shown in the
controlled-run block. The quarantine unit is pulled in by `OnFailure`; do not
enable it independently.

The example uses `Persistent=false`, so it does not catch up an event missed
while the timer was inactive or the host was powered off. That setting alone
does not prevent a calendar timer firing immediately after suspend or
hibernate. The approval guard therefore removes the marker and, through the
timer's `BindsTo=`, stops the timer before sleep, systemd soft reboot or
shutdown. A kernel reboot also clears `/run`. After any such transition, the
operator must inspect and stop any timer restarted by `timers.target`, verify
the marker is absent, revalidate the host and explicitly restart the
timer/guard before creating a new marker. An automatically restarted timer
without its marker cannot start a loader. The marker must never be recreated
automatically.
Changing `Persistent` to `true` requires an explicit BRERC catch-up decision and
a separate reviewed crash/reboot safety design.

## Failure and rollback

1. A failed `brerc-loader-refresh.service` must start
   `brerc-loader-refresh-quarantine.service`, which removes only
   `/run/brerc/refresh/APPROVED_TO_SCHEDULE`. Verify both the quarantine unit's
   successful status and the marker's absence. If either check fails, stop and
   disable `brerc-loader-refresh.timer` and have an authorised root operator
   remove that exact marker. Preserve the invocation-scoped journal and database
   evidence. Never use a wildcard or remove any other file in the configuration
   directory.
2. For failure, maintenance or cancellation, use this mandatory disarm order:
   stop and disable the timer, stop the approval guard, verify the marker is
   absent, and only then stop a running loader. Although a timer that remains
   enabled cannot pass the missing-marker condition, disabling it and stopping
   the guard prevents a race while an operator deliberately re-arms the
   schedule:

   ```sh
   systemctl disable --now brerc-loader-refresh.timer
   systemctl stop brerc-loader-refresh-approval-guard.service
   test ! -e /run/brerc/refresh/APPROVED_TO_SCHEDULE
   case "$(systemctl show brerc-loader-refresh.service --property=ActiveState --value)" in
     active|activating|deactivating) systemctl stop brerc-loader-refresh.service ;;
     failed|inactive) ;; # Preserve a terminal failed invocation for evidence.
     *) echo 'unknown loader state; escalate without resetting it' >&2; exit 1 ;;
   esac
   ```

   An operator-initiated stop, shutdown or cancellation does not necessarily
   leave systemd in `failed` state and therefore may not start `OnFailure` or
   satisfy the failed-attempt verifier. Preserve the exact journal, query the
   database/API state and escalate; if the unit is inactive/successful, do not
   claim verified zero-job evidence and do not use that attempt to authorise a
   retry. Only an exact invocation that remains `failed` can use the failure
   verifier below.
3. If a refresh failed, verify the previous release is still active through the
   API identity and safe structural counts. Do not move a `serve.*` pointer with
   manual SQL, run the legacy nightly path, use a force flag or edit a manifest.
   For the attended rehearsal, use the invocation, database-clock window and
   protected evidence directory already captured above. For a later unattended
   scheduled failure, collect evidence in a new protected shell **before** any
   `systemctl reset-failed`, restart or host reboot. Set the window from that
   exact scheduler occurrence, alert record and approved timeout—not from an
   earlier attempt. A logout is safe because systemd/journald retain the live
   invocation; a reboot is not supported by this recovery path because current
   unit state is lost. The volatile marker prevents a post-reboot retry. After a
   reboot, or whenever an exact failed invocation and unambiguous positive
   window of at most four hours cannot be established, stop, preserve the
   journal/database and escalate: do not claim a zero-job result or re-arm.
   The Linux host and PostgreSQL clocks must be synchronised; every journal and
   systemd manager lifecycle timestamp must fall within 60 seconds of the
   database-clock window or the verifier rejects the bundle.

   In either path, set the three expected identity values from the approved
   deployment record, never by copying query output. Run the bounded query and
   verifier as follows; all uppercase values are mandatory replacements:

   For an unattended failure only, run this setup block in a new dedicated
   root Bash shell with fresh values. Skip it during the attended rehearsal
   because those variables and the new directory already belong to that
   attempt. A failed command stops the shell; preserve any partial evidence
   and escalate rather than reusing its directory:

   ```bash
   set -euo pipefail
   set -C  # Do not overwrite an existing evidence file.
   evidence=NEW_CONTROLLED_EVIDENCE_DIRECTORY
   database_window_start=SCHEDULED_WINDOW_START_UTC
   database_window_end=SCHEDULED_WINDOW_END_UTC
   expected_environment_id=APPROVED_DESTINATION_ENVIRONMENT_UUID
   expected_database=APPROVED_DESTINATION_DATABASE_NAME
   expected_monitor_role=APPROVED_MONITOR_LOGIN_ROLE
   invocation_id=EXACT_FAILED_INVOCATION_ID
   case "$evidence" in /*) ;; *) exit 1 ;; esac
   umask 077
   mkdir -m 0700 -- "$evidence"  # Existing directory/symlink is a hard stop.
   chown root:root -- "$evidence"
   ```

   Then run the common validation block. It fails if any value or protected
   directory is missing:

   ```sh
   : "${evidence:?missing evidence directory}"
   : "${database_window_start:?missing start time}"
   : "${database_window_end:?missing end time}"
   : "${expected_environment_id:?missing environment identity}"
   : "${expected_database:?missing database name}"
   : "${expected_monitor_role:?missing monitor role}"
   : "${invocation_id:?missing InvocationID}"
   [ "$(stat -c '%U:%G:%a' -- "$evidence")" = root:root:700 ] || exit 1
   case "$database_window_start" in
     ????-??-??T??:??:??.??????Z) ;; *) exit 1 ;; esac
   case "$database_window_end" in
     ????-??-??T??:??:??.??????Z) ;; *) exit 1 ;; esac
   case "$invocation_id" in
     [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
     *) exit 1 ;;
   esac
   observed_invocation_id="$(
     systemctl show brerc-loader-refresh.service --property=InvocationID --value
   )"
   [ "$observed_invocation_id" = "$invocation_id" ] || exit 1
   systemctl show --timestamp=unix brerc-loader-refresh.service \
     --property=InvocationID --property=Result --property=ExecMainCode \
     --property=ExecMainStatus --property=ActiveState --property=SubState \
     --property=InactiveExitTimestamp --property=StateChangeTimestamp \
     > "$evidence/unit.properties"
   journalctl _SYSTEMD_INVOCATION_ID="$invocation_id" --output=json \
     > "$evidence/journal.json"
   printf '{"invocationId":"%s","mode":"refresh","windowStart":"%s","windowEnd":"%s"}\n' \
     "$invocation_id" "$database_window_start" "$database_window_end" \
     > "$evidence/database-window.json"
   psql -X -v ON_ERROR_STOP=1 \
     --dbname='service=APPROVED_MONITOR_SERVICE' \
     --tuples-only --no-align \
     --set=window_start="$database_window_start" \
     --set=window_end="$database_window_end" \
     --set=load_mode=refresh \
     --set=expected_environment_id="$expected_environment_id" \
     --set=expected_database="$expected_database" \
     --set=expected_role="$expected_monitor_role" \
     --file=/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/failed_attempt_evidence_query.sql \
     > "$evidence/database-failure.json"
   python3 /opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/verify_failed_attempt_evidence.py \
     --invocation-id "$invocation_id" \
     --mode refresh \
     --expected-window-start "$database_window_start" \
     --expected-window-end "$database_window_end" \
     --expected-environment-id "$expected_environment_id" \
     --expected-database "$expected_database" \
     --expected-role "$expected_monitor_role" \
     --unit-properties "$evidence/unit.properties" \
     --journal-json "$evidence/journal.json" \
     --database-window-json "$evidence/database-window.json" \
     --database-json "$evidence/database-failure.json"
   ```

   Require exactly zero jobs (failure before database acquisition) or one
   matching terminal failed/cancelled job. The verifier rejects an invalid or
   over-four-hour or mismatched invocation/window, a successful or nonterminal
   systemd state, an invalid mode, wrong database/environment/session
   privileges, multiple jobs,
   nonterminal/successful jobs, cleanup debt and malformed or extra fields. Its
   success validates a coherent protected evidence bundle but is not a
   cryptographic replay-prevention registry and does not authorise re-arming.
   Retain it in the organisation's immutable/single-use evidence system. If the API
   names a newer release despite a failed/cancelled systemd result, activation
   committed and the database/API identity is authoritative—do not attempt to
   undo it with manual SQL.
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
service state, start and verify the approval guard and timer while the marker is
absent, confirm the next scheduled trigger is outside the attended window,
then create a new root-controlled `APPROVED_TO_SCHEDULE` marker and perform one
attended refresh. Only after that refresh succeeds and its release identity is
reconciled may the schedule remain armed. Never configure
`Restart=` on the loader or quarantine units and never recreate the marker from
an `ExecStopPost`, notification worker or timer hook.

Removing the timer later does not authorise deleting configuration, credentials,
logs or evidence. Their retention and secure destruction remain with the named
service and data owners.
