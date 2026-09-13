# First production publication load: operator addendum

This is a deliberately inert example for one *observed* `brerc-load initial`
attempt, not a scheduled deployment. The only tracked unit ends in `.example`;
there is no timer or automatic retry. Checking out this repository installs
nothing. The separate root-controlled
`/etc/brerc/refresh/APPROVED_TO_INITIAL` marker is required before systemd can
start the service; `APPROVED_TO_SCHEDULE` does **not** authorise an initial load.

The marker is a manual approval gate, **not** an automatically consumed token.
While it remains present, an operator could start the unit again after it exits.
Remove it immediately after *every* start attempt, whether the attempt succeeds
or fails. A retry requires investigation, a new approval and a new marker. The
loader/database independently refuses `initial` once an active release exists;
that guard does not replace removal of the marker.

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
   ending `.service`. Run `systemd-analyze verify` and review
   `systemd-analyze security` on the intended production systemd version. Do
   not remove hardening directives without a documented security review.
2. With approvals complete, install only
   `/etc/systemd/system/brerc-loader-initial.service` as `root:root` mode `0644`.
   Do not install or enable a timer. Verify the installed unit still invokes
   only `brerc-load initial` and references the reviewed release and config.
3. In the approved window, have the operator create only
   `/etc/brerc/refresh/APPROVED_TO_INITIAL` as `root:brerc-loader` mode `0440`,
   then `systemctl daemon-reload` and start the service once with an observer.
   This is a real publication attempt, never a dry run. Never source the
   environment file into an interactive shell.
4. As soon as `systemctl start brerc-loader-initial.service` returns, remove the
   exact `APPROVED_TO_INITIAL` marker **even if the command failed**. The
   observer must verify its absence and must not retry from shell history or
   restart the service. Record the result with `systemctl status` and
   `journalctl -u brerc-loader-initial.service`, exporting only redacted data.

Check exit status zero together with the fixed loader result fields
`status:"ok"`, `state:"succeeded"`, `mode:"initial"` and `activated:true`. Verify the first
active release through the read-only API, its `releaseId`/`datasetVersion`
coherence and a real dashboard smoke check with browser mocks disabled. Retain
the approval record, digests, redacted job/release IDs, source snapshot time,
privacy-safe structural counts, start/end time, timeout and terminal state under
the organisation's restricted evidence policy. Do not retain raw source rows,
coordinates, personal data, credentials, DSNs or unredacted exceptions.

If the attempt fails, keep the marker absent and confirm no active release was
published. Preserve the journal and database run history; investigate the
failure and any inactive cleanup debt before considering a separately approved
`initial` retry. Do not use `--force`, edit a manifest, manually move the
`serve.*` pointer or fall back to the legacy nightly job. After a successful
initial load, only the separately approved full-snapshot `refresh` path may
replace it; this initial unit remains unenabled and should not be reused.
