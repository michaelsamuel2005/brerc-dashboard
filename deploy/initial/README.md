# First production publication load: operator addendum

This is a deliberately inert example for one *observed* `brerc-load initial`
attempt, not a scheduled deployment. Both tracked units end in `.example`;
there is no timer or automatic retry. Checking out this repository installs
nothing. The second unit is a fixed failure quarantine whose only command
removes the approval marker; it is never enabled independently. The separate root-controlled
`/etc/brerc/initial-approval/APPROVED_TO_INITIAL` marker is required before the
pre-start gate permits the loader to execute; `APPROVED_TO_SCHEDULE` does
**not** authorise an initial load. A missing or invalid marker fails the unit;
it is never reported as a clean condition skip.

The marker is a **single-use**, time-limited manual approval gate. The fixed,
separately installed root-owned `ExecStartPre` helper verifies its exact schema,
approval reference, immutable artifact ID and UTC validity window, then durably
consumes it before the loader starts. The permitted window is at most four hours
and the marker authorises only the artifact rendered into the unit. Once the
helper validates and consumes it, the marker stays absent through loader
success, failure, timeout, cancellation or an operator disconnect. A missing or
invalid marker fails the service, and the subsequent asynchronous `OnFailure`
quarantine removes that exact path. Operators must wait for the quarantine unit
and verify marker absence before resetting or restarting anything. A retry
requires investigation, a new approval and a new marker. The loader/database
independently refuses `initial` once an active release exists; that guard does
not replace the one-attempt approval boundary.

## Inputs and approval gate

Use the same dedicated `brerc-loader` account, read-only reviewed application
release, protected `/etc/brerc/refresh` files, secret-store export, distinct
source/target passfiles and CAs, `verify-full` TLS and hardening rules specified
in [`../refresh/README.md`](../refresh/README.md). Do not copy credentials into
this directory or create an initial-specific environment file. The approved
loader configuration must bind the exact source, destination, policy and
dictionary, approved *initial* row bounds, and all separately required refresh
thresholds. The example's 2h15m timeout is not production approval: set it only
after reviewing retained scale evidence and the authorised runtime window.

Before installing or starting the unit, the accountable owner must approve and
record the exact protected-main commit and immutable artifact digest, production
host, operator/observer, maintenance window, timeout, source/destination role
identities, policy/dictionary digests, initial bounds, privacy acceptance and
rollback contact. The separately authorised real BRERC rehearsal must already
have passed on a network-dark acceptance destination with its own environment
identity; that rehearsal is not this production attempt. Confirm the production
destination migrations are current and **no active release** exists. Confirm
the source view and read-only account match the approved 39-column contract.
Independently check the file ownership/modes and
database identities described in the refresh runbook. Neither these templates
nor a green synthetic run constitute BRERC production approval.

Migration `0004` and this compatible loader artifact must be installed as one
forward-only maintenance change. An older loader that expects only migrations
1–3 cannot run afterward. There is no down migration; application recovery must
use another reviewed four-migration artifact, while database rollback is a DBA
whole-database restore under the incident plan.

## Controlled first attempt

1. Verify the exact system interpreter used by `ExecStartPre`; checking the
   application virtual environment is not sufficient. The approval helper
   requires Python 3.10 or newer, and an older interpreter blocks the attempt:

   ```sh
   test -x /usr/bin/python3
   /usr/bin/python3 --version
   /usr/bin/python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'
   ```

   From the exact approved release, install a standalone copy of the helper at
   the fixed path used by the unit. It must not execute from the application
   release because this one command runs with UID 0. Record its digest in the
   approval record, and require the helper and every parent directory to be
   root-owned and not writable by any non-root identity:

   ```sh
   install -d -o root -g root -m 0755 /usr/local/libexec/brerc
   install -o root -g root -m 0555 \
     /opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/initial/consume_initial_approval.py \
     /usr/local/libexec/brerc/consume-initial-approval.py
   namei -l /usr/local/libexec/brerc/consume-initial-approval.py
   sha256sum /usr/local/libexec/brerc/consume-initial-approval.py
   ```

   Reject a symlink, unexpected owner/mode or digest mismatch. The installed
   SHA-256 must equal the approved standalone-helper digest. The unit invokes
   the helper through an empty environment, Python `-I` and systemd's `!`
   prefix: loader database/HMAC secrets are not inherited, only its UID/GID
   exception is permitted, and the service's filesystem and other sandbox
   controls remain.
2. Copy both `.service.example` files to protected staging names ending
   `.service`. Replace every `REPLACE_WITH_APPROVED_ARTIFACT_ID` in the loader
   unit with
   the exact immutable release-directory identifier and verify no placeholder,
   `current` path or symlink remains. Run `systemd-analyze verify` and
   `systemd-analyze security --threshold=40 --no-pager` on both units with the
   intended production systemd version. The threshold is rendered as exposure
   4.0; the reviewed Ubuntu 24.04 baseline scores 3.2 and 2.5. Do not remove
   hardening directives without a documented security review.
3. With approvals complete, install only
   `/etc/systemd/system/brerc-loader-initial.service` and
   `/etc/systemd/system/brerc-loader-initial-quarantine.service` as `root:root`
   mode `0644`.
   Do not install or enable a timer. Run `systemctl daemon-reload`, then capture
   the effective definition and provenance of **both** units:

   ```sh
   for unit in \
     brerc-loader-initial.service \
     brerc-loader-initial-quarantine.service
   do
     systemctl cat "$unit"
     systemctl show "$unit" --property=FragmentPath --property=DropInPaths
   done
   sha256sum \
     /etc/systemd/system/brerc-loader-initial.service \
     /etc/systemd/system/brerc-loader-initial-quarantine.service
   ```

   For each unit, require the fragment to be the installed file,
   `DropInPaths=` to be empty, and the installed SHA-256 to equal its approved
   unit-file digest. Reconfirm the fixed helper's owner, parent modes and digest
   immediately before the attempt. Re-run
   `systemd-analyze verify` on both installed units and record
   `systemd-analyze security --threshold=40 --no-pager` for both on the target
   host. Reject a score above 4.0, any drop-in, alias, unresolved placeholder,
   mutable path or command difference; the effective unit must invoke only the
   reviewed `brerc-load initial` artifact and config.
4. In the approved window, create the dedicated approval directory as
   `root:root` mode `0700`. Immediately before the observed start, have the
   operator create `/etc/brerc/initial-approval/APPROVED_TO_INITIAL` as
   `root:root` mode `0400`, containing exactly this non-secret JSON shape (with
   real approved values and UTC timestamps):

   ```json
   {"schemaVersion":1,"approvalReference":"BRERC-CHANGE-123","artifactId":"APPROVED_ARTIFACT_ID","validFromUtc":"2026-09-18T19:55:00Z","expiresAtUtc":"2026-09-18T22:55:00Z"}
   ```

   The file must be regular, single-linked and no larger than 4096 bytes. Its
   validity interval must be positive and no longer than four hours. The
   reference points to the separately protected approval record; that record
   and any secrets do not belong in this marker.
5. If approval is withdrawn before start, an authorised root operator must run
   `rm -f -- /etc/brerc/initial-approval/APPROVED_TO_INITIAL`, verify the path is
   absent and record the withdrawal. If withdrawal arrives after
   `ExecStartPre` consumed the marker, immediately stop the unit, preserve the
   invocation-scoped evidence, and reconcile database/API state before deciding
   anything else: cancellation cannot undo an activation that already committed.
   Never recreate a marker for the same approval. An operator-initiated stop
   does not necessarily leave systemd in `failed` state or activate
   `OnFailure`. If it ends inactive/successful, preserve the journal and query
   the database/API state, but do not claim verified zero-job evidence and do
   not use that attempt to authorise a retry. The failed-attempt verifier is
   valid only when the exact invocation remains in `failed` state.
6. Record the previous `InvocationID`, then capture `database_window_start`
   from the database clock through the protected monitor service. The Linux
   host and PostgreSQL clocks must be synchronised: the verifier requires the
   journal and systemd manager lifecycle timestamps to fall within 60 seconds
   of this database-clock window. Run steps 6–8 in one dedicated root Bash
   shell. Use a new absolute evidence directory that does not already exist;
   never reuse a directory from an earlier or interrupted attempt. The shell
   must exit on any failed command, unset variable or pipeline. If it exits
   part-way through, preserve the partial bundle and reconcile the unit,
   database and API state before doing anything else; do not paste the next
   block into a fresh shell or retry the start.

   ```bash
   set -euo pipefail
   set -C  # Do not overwrite an existing evidence file.
   unit=brerc-loader-initial.service
   quarantine=brerc-loader-initial-quarantine.service
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
   if [ "$loader_result" != success ]; then
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
   test ! -e /etc/brerc/initial-approval/APPROVED_TO_INITIAL
   ```

   The nonblocking start plus the `Job` poll waits for this exact oneshot to
   reach a terminal state without treating a loader failure as permission to
   skip evidence capture. Start it once with an observer. This is a real
   publication attempt, never a dry run. Never source the environment file
   into an interactive shell. The helper consumes the marker before Python
   opens either database. Verify the marker is absent while the unit runs and
   after it exits. On success, `RemainAfterExit=yes` deliberately keeps the
   unit `active (exited)` so its invocation identity and lifecycle timestamps
   remain available until evidence verification finishes. Do not recreate the
   marker or retry from shell history.
7. Capture only this attempt in the new root-owned directory created above:

   ```sh
   unit=brerc-loader-initial.service
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
   printf '{"invocationId":"%s","mode":"initial","windowStart":"%s","windowEnd":"%s"}\n' \
     "$invocation_id" "$database_window_start" "$database_window_end" \
     > "$evidence/database-window.json"
   journalctl _SYSTEMD_INVOCATION_ID="$invocation_id" --output=json \
     > "$evidence/journal.json"
   ```

   Confirm the new ID is non-empty and differs from the recorded previous ID.
   Do not use `journalctl -u` as acceptance evidence because it mixes attempts.
8. Extract the single fixed loader result document from the restricted journal
   and take its `runId`. Query only the migration-0004 evidence view through the
   protected monitor service:

   ```sh
   run_id="$(jq -ers --arg id "$invocation_id" '
     [.[] | select(._SYSTEMD_INVOCATION_ID == $id) |
      (.MESSAGE | fromjson?) |
      select(.status == "ok" and .state == "succeeded" and .mode == "initial")]
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
     --invocation-id "$invocation_id" --mode initial \
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

   Replace `APPROVED_ARTIFACT_ID` with the same immutable, digest-bound release
   directory rendered into the installed unit; it must not be a symlink.

   After the verifier succeeds and the evidence bundle is retained, unload the
   one-shot unit and confirm that it is inactive. Do this only after capture,
   because stopping it changes or clears the lifecycle properties needed by
   the verifier:

   ```sh
   systemctl stop brerc-loader-initial.service
   [ "$(systemctl is-active brerc-loader-initial.service)" = inactive ] || exit 1
   [ "$(systemctl show brerc-loader-initial.service --property=SubState --value)" = dead ] || exit 1
   test ! -e /etc/brerc/initial-approval/APPROVED_TO_INITIAL
   ```

The verifier requires a successful terminal systemd state together with the
fixed loader result fields `status:"ok"`, `state:"succeeded"`,
`mode:"initial"`, `activated:true` and `reusedActiveRelease:false`. It binds the
one invocation to the database job, active release, candidate digest, source
snapshot time and both read-only API identities. Verify a real dashboard smoke
check with browser mocks disabled. Retain the approval record, digests, effective
unit text/properties/security report, redacted job/release IDs, source snapshot time,
privacy-safe structural counts, start/end time, timeout and terminal state under
the organisation's restricted evidence policy. Do not retain raw source rows,
coordinates, personal data, credentials, DSNs or unredacted exceptions.

If the loader attempt fails, the marker must be absent when the unit and its
quarantine reach terminal states.
The loader unit's `OnFailure` must also start
`brerc-loader-initial-quarantine.service`, so a prerequisite or execution
failure that occurs before the root approval helper removes the exact marker as
well. The prerequisites are fixed, shell-free `ExecStartPre=/usr/bin/test`
commands because systemd `Assert*` failures do not activate `OnFailure`. Verify the
quarantine result and marker absence; do not enable the quarantine unit.
Use the already captured `database_window_start` and `database_window_end`, then
run the bounded monitor query. Set the three non-secret expected identity values
from the approved deployment record, never by inferring them from query output:

```sh
expected_environment_id=APPROVED_DESTINATION_ENVIRONMENT_UUID
expected_database=APPROVED_DESTINATION_DATABASE_NAME
expected_monitor_role=APPROVED_MONITOR_LOGIN_ROLE
psql -X -v ON_ERROR_STOP=1 \
  --dbname='service=APPROVED_MONITOR_SERVICE' \
  --tuples-only --no-align \
  --set=window_start="$database_window_start" \
  --set=window_end="$database_window_end" \
  --set=load_mode=initial \
  --set=expected_environment_id="$expected_environment_id" \
  --set=expected_database="$expected_database" \
  --set=expected_role="$expected_monitor_role" \
  --file=/opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/failed_attempt_evidence_query.sql \
  > "$evidence/database-failure.json"
python3 /opt/brerc-dashboard/releases/APPROVED_ARTIFACT_ID/deploy/validation/verify_failed_attempt_evidence.py \
  --invocation-id "$invocation_id" \
  --mode initial \
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

Require either zero database jobs (failure before database acquisition) or
exactly one job matching the approved source, `initial` mode and observed
window. The verifier rejects an invalid or over-four-hour window, a mismatched
invocation/window, a successful or nonterminal systemd state, an invalid mode,
wrong database/environment/session privileges, multiple jobs,
nonterminal/successful jobs, cleanup debt and malformed or extra fields. Its
success validates a coherent protected evidence bundle; it is not a
cryptographic replay-prevention registry and does not authorise a retry. Retain
it in the organisation's immutable/single-use evidence system. Retain only the
fixed identity, status, failure code, safe
counts and cleanup flag. Check `/api/summary` and `/api/meta/provenance` as the
authoritative publication state. If an active release exists despite a systemd
failure or cancellation, activation committed: do **not** retry `initial`; treat
the database/API identity as authoritative and escalate the incident. If no
release is active, investigate the failure and any inactive cleanup debt before
a separately approved retry. Do not use `--force`, edit a manifest, manually
move the `serve.*` pointer or fall back to the legacy nightly job. After a
successful initial load, only the separately approved full-snapshot `refresh`
path may replace it; this initial unit remains unenabled and should not be
reused.
