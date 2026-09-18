# First production publication load: operator addendum

This is a deliberately inert example for one *observed* `brerc-load initial`
attempt, not a scheduled deployment. The only tracked unit ends in `.example`;
there is no timer or automatic retry. Checking out this repository installs
nothing. The separate root-controlled
`/etc/brerc/initial-approval/APPROVED_TO_INITIAL` marker is required before the
pre-start gate permits the loader to execute; `APPROVED_TO_SCHEDULE` does
**not** authorise an initial load. A missing or invalid marker fails the unit;
it is never reported as a clean condition skip.

The marker is a **single-use** manual approval gate. The fixed
`ExecStartPre` helper validates and durably consumes it before the loader
starts. It stays absent after success, failure, timeout, cancellation or an
operator disconnect. A retry requires investigation, a new approval and a new
marker. The loader/database independently refuses `initial` once an active
release exists; that guard does not replace the one-attempt approval boundary.

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

## Controlled first attempt

1. Copy `brerc-loader-initial.service.example` to a protected staging name
   ending `.service`. Replace every `REPLACE_WITH_APPROVED_ARTIFACT_ID` with
   the exact immutable release-directory identifier and verify no placeholder,
   `current` path or symlink remains. Run `systemd-analyze verify` and review
   `systemd-analyze security` on the intended production systemd version. Do
   not remove hardening directives without a documented security review.
2. With approvals complete, install only
   `/etc/systemd/system/brerc-loader-initial.service` as `root:root` mode `0644`.
   Do not install or enable a timer. Verify the installed unit still invokes
   only `brerc-load initial` and references the reviewed release and config.
3. In the approved window, create the dedicated approval directory as
   `root:root` mode `0700`, then have the operator create a non-secret approval
   reference in `/etc/brerc/initial-approval/APPROVED_TO_INITIAL` as
   `root:root` mode `0400`. The file must be non-empty, regular and
   single-linked. The reference binds the separately protected approval record;
   the approval record itself does not belong in this runtime marker.
4. Record the previous `InvocationID`, run `systemctl daemon-reload`, then start
   the service once with an observer. This is a real publication attempt, never
   a dry run. Never source the environment file into an interactive shell.
   The helper consumes the marker before Python opens either database. Verify
   the marker is absent while the unit runs and after it exits. Do not recreate
   it or retry from shell history.
5. Capture only this attempt. Replace `CONTROLLED_EVIDENCE_DIRECTORY` with a
   root-owned, access-controlled directory outside the repository:

   ```sh
   unit=brerc-loader-initial.service
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
   ```

   Confirm the new ID is non-empty and differs from the recorded previous ID.
   Do not use `journalctl -u` as acceptance evidence because it mixes attempts.
6. Extract the single fixed loader result document from the restricted journal
   and take its `runId`. Query only the migration-0004 evidence view through the
   protected monitor service:

   ```sh
   run_id="$(jq -ers --arg id "$invocation_id" '
     [.[] | select(._SYSTEMD_INVOCATION_ID == $id) |
      (.MESSAGE | fromjson?) |
      select(.status == "ok" and .state == "succeeded" and .mode == "initial")]
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
     --invocation-id "$invocation_id" --mode initial \
     --unit-properties "$evidence/unit.properties" \
     --journal-json "$evidence/journal.json" \
     --database-json "$evidence/database.json" \
     --api-summary-json "$evidence/api-summary.json" \
     --api-provenance-json "$evidence/api-provenance.json"
   ```

   Replace `APPROVED_ARTIFACT_ID` with the same immutable, digest-bound release
   directory rendered into the installed unit; it must not be a symlink.

The verifier requires a successful terminal systemd state together with the
fixed loader result fields `status:"ok"`, `state:"succeeded"`,
`mode:"initial"`, `activated:true` and `reusedActiveRelease:false`. It binds the
one invocation to the database job, active release, candidate digest and both
read-only API identities. Verify a real dashboard smoke check with browser
mocks disabled. Retain
the approval record, digests, redacted job/release IDs, source snapshot time,
privacy-safe structural counts, start/end time, timeout and terminal state under
the organisation's restricted evidence policy. Do not retain raw source rows,
coordinates, personal data, credentials, DSNs or unredacted exceptions.

If the attempt fails, the marker remains absent; confirm no active release was
published. Preserve the invocation-scoped journal and database run history;
investigate the
failure and any inactive cleanup debt before considering a separately approved
`initial` retry. Do not use `--force`, edit a manifest, manually move the
`serve.*` pointer or fall back to the legacy nightly job. After a successful
initial load, only the separately approved full-snapshot `refresh` path may
replace it; this initial unit remains unenabled and should not be reused.
