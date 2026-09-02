# Monitoring and notification worker

## Current status

The repository implementation and synthetic acceptance gates can be completed
without BRERC credentials or email addresses. **Production delivery is not yet
complete.** Verified on 26 August 2026:

- protected `main` is `01b2ef7fbdc37d5230668f6b70bb6ef3930469eb`;
- GitHub has only the `brerc-scale-acceptance` environment and no production
  environment or Actions secret names;
- the publication outbox and role design are waiting to land through issue #40;
- issue #46 still requires the real private PostgreSQL/PostGIS service, verified
  database TLS, named recipients, escalation route and operational owner.

Do not add BRERC addresses, passwords, DSNs, private hostnames, certificate
private keys or controlled evidence to Git, GitHub, email or chat. Do not report
unit tests, a local SMTP sink or a green pull request as a delivered production
notification.

## What the worker does

For each terminal publication job, the loader and database atomically create
one safe outbox event. The worker then:

1. claims an available event under a time-limited database lease;
2. resolves its destination alias from a mounted controlled configuration;
3. builds a plain-text message from fixed fields only;
4. submits it using verified SMTP TLS or the approved HTTPS webhook;
5. acknowledges the exact lease on acceptance, or records a fixed failure code
   and lets the database schedule a retry/dead-letter transition; and
6. reports private liveness, readiness and fixed-label metrics.

The worker never reads the BRERC source database or occurrence tables. It does
not send arbitrary exception strings. It does not expose an HTTP route through
Caddy. See the architecture decision in
[`architecture/ADR-2026-08-26-transactional-notification-outbox.md`](architecture/ADR-2026-08-26-transactional-notification-outbox.md).

## Deployment topology

```text
publication loader
       |
       | terminal state + outbox row (one transaction)
       v
private PostgreSQL/PostGIS <--- verify-full TLS ---> notifier container
                                                        |
                                                        | verified SMTP TLS
                                                        v
                                               approved delivery provider

independent monitor ---> public dashboard HTTPS / certificate / host / backup
                    `--> private notifier readiness + dead-man signal
```

Only the dashboard's Caddy service is public. Port `9108` has no host `ports:`
mapping. It is reachable only by explicitly joined containers on the two
private networks (database and notifier control), and Caddy must not join either
network. The production host firewall restricts notifier egress to the approved
SMTP/webhook endpoint; network membership is restricted to the database,
notifier and authorised collector.

## Configuration contract

The focused deployment overlay is
[`deploy/notifier.compose.yaml`](../deploy/notifier.compose.yaml). It expects a
controlled notifier configuration mounted as a Compose secret at
`/run/secrets/notifier-config`. Start from
[`api/notifier.configuration.example.yaml`](../api/notifier.configuration.example.yaml),
keep the real copy outside the repository and mount it for container UID/GID
`65532:65532` at mode `0400`; see the Compose file-source caveat in
[`deploy/notifier/README.md`](../deploy/notifier/README.md).

Production configuration must provide:

| Item | Requirement |
| --- | --- |
| Database | Dedicated notifier login; private DNS; PostgreSQL `sslmode=verify-full`; approved CA; bounded connect and statement timeouts. |
| Database capability | Membership only in the reviewed notifier group; execute-only claim/ack/retry surface; no base-table reads or direct outbox writes. |
| Delivery | Approved SMTP hostname/port with verified TLS, or an approved HTTPS webhook; credentials are separate controlled files. Email requires a BRERC/BCC-authorised From address. |
| Destinations | The v1 alias `etl-operations` maps to exactly one approved mailbox or managed distribution list outside the database/repository. Multiple direct recipients are rejected to avoid partial-delivery ambiguity. |
| URLs | Optional internal run-history link only if its access and hostname are approved; never place source/database details in the message. |
| Ownership | Named service owner, operational operator, recipients, incident owner, escalation path and response targets. |

The libpq service file is fail-closed: it contains exactly one configured
section with `host`, `port`, `dbname`, `user` and `sslmode=verify-full`. The
database/login values must match the notifier YAML. Passwords, extra libpq
options and additional service sections are rejected; the protected passfile
is the only database-password source.

Version 1 requires `runtime.batch_size: 1`. A worker delivers sequentially and
must acknowledge or fail the current lease before claiming work for another
provider call. Per-claim renewal protects the one active delivery; it does not
make it safe to claim a waiting batch whose later leases would age before their
provider calls. A larger batch requires a separately reviewed bounded-parallel
design and real PostgreSQL concurrency evidence after #40.

While a provider call is active, a separate bounded thread renews that exact
notification UUID/claim-token lease. Configuration requires enough lease margin
for both provider and database operations. A renewal failure is a fixed-code
counter/log event; the eventual acknowledgement remains token-bound and a stale
worker cannot acknowledge a reclaimed lease.

The checked-in template contains no working host, address or credential. Local
test values are not production defaults. The focused Compose overlay wires the
recommended SMTP profile. An HTTPS-webhook deployment must replace the two SMTP
secret mounts with `BRERC_NOTIFIER_WEBHOOK_SECRET_FILE` in a separately reviewed
overlay; do not create dummy SMTP credentials to satisfy the example.

### Database installation order

Issue #40 must retain the publication migration as the owner of event truth.
The notification additions are applied around it in this exact order on a new
database:

1. `db/roles.sql` — publication capability roles from #40;
2. `db/notifier_roles.sql` — `brerc_notifier` and the separately controlled
   `brerc_notifier_operator` capability;
3. `db/migrations/0001_publication_store.sql` — jobs, releases and outbox; and
4. `db/migrations/0002_notification_delivery.sql` — leases, bounded retry,
   metrics and execute-only delivery functions.

For an existing database already at migration 0001, apply notifier roles and
then migration 0002 with `psql -v ON_ERROR_STOP=1`. Never edit migration history
or apply 0002 to the legacy `db/b6_schema.sql` database.

The service login inherits only `brerc_notifier`. The human break-glass login
for a reviewed dead-letter requeue inherits only `brerc_notifier_operator` and
is not configured in the worker. Migration 0002 gives the notifier exactly six
functions:

- `claim_notifications(int, int)`;
- `renew_notification_lease(uuid, uuid, int)`;
- `ack_notification(uuid, uuid)`;
- `fail_notification(uuid, uuid, text, int)`;
- redacted `notification_delivery_metrics()`; and
- `notification_worker_preflight()`.

The separate operator capability receives only
`requeue_dead_notification(uuid, text)` and the redacted metrics function.

The notifier's exact six-function capability applies within the four
application schemas (`loader_control`, `loader_stage`, `publication`, `serve`);
PostGIS and PostgreSQL system routines are outside that count. No notifier
capability receives table privileges. A stale or mismatched lease token must be
rejected rather than treated as a harmless duplicate.
Dead-letter redrive is a reviewed break-glass action, never an automatic worker
operation. Its reason must be exactly one of `DESTINATION_REMEDIATED`,
`CREDENTIAL_ROTATED`, `PROVIDER_RECOVERED` or `MANUAL_REDRIVE_APPROVED`.

### PostgreSQL 16 login and cluster ACL gate

PostgreSQL grants `CONNECT` and `TEMPORARY` on newly created databases to
`PUBLIC` by default. The notifier preflight deliberately rejects that broad
posture: the notifier login must have only direct `CONNECT` to the publication
database, no `TEMPORARY`/`CREATE`, and no effective `CONNECT` to any other
connectable database. PostgreSQL 16 also records `ADMIN`, `INHERIT` and `SET`
per role membership. Provision the service membership exactly as:

```sql
GRANT brerc_notifier TO brerc_notifier_service
WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
```

The login must be `LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
NOREPLICATION NOBYPASSRLS`, own no database object, have no per-role settings,
and have no other role membership. Use the deployment's real, separately
created login name in both the grant and controlled notifier configuration.

This is a **cluster-impacting DBA change**, not a copy-paste migration. Before
revoking anything, inventory every API, loader, backup, migration and human
administrator that legitimately connects. Then, in a reviewed maintenance
change:

1. revoke `TEMPORARY` and broad `PUBLIC CONNECT` on the publication database;
2. grant direct `CONNECT` back to every legitimate service/administrator,
   including exactly one direct grant to the notifier login;
3. inventory every other `datallowconn` database, revoke broad `PUBLIC CONNECT`
   where approved, and explicitly restore its legitimate users—but never the
   notifier login or notifier capability; and
4. constrain `pg_hba.conf` so the notifier login can reach only the publication
   database from its approved source over TLS, then reload and independently
   verify every preserved API/loader/admin path.

Do not run a blanket revoke until that inventory and recovery access are
reviewed. The SQL ACL and `pg_hba.conf` checks are complementary: PostgreSQL
checks `CONNECT` at session startup in addition to HBA restrictions.

Use quoted psql identifier variables so a database or login name cannot become
SQL. The DBA must add **every** legitimate current role to the same transaction
before committing; the names below are illustrative, not repository defaults:

```sql
\set publication_database 'REPLACE_AFTER_INVENTORY'
\set notifier_login 'REPLACE_WITH_DEDICATED_LOGIN'
\set api_login 'REPLACE_WITH_API_LOGIN'
\set loader_login 'REPLACE_WITH_LOADER_LOGIN'
\set admin_login 'REPLACE_WITH_RECOVERY_ADMIN'

BEGIN;
REVOKE TEMPORARY, CONNECT
ON DATABASE :"publication_database" FROM PUBLIC;
GRANT CONNECT
ON DATABASE :"publication_database"
TO :"notifier_login", :"api_login", :"loader_login", :"admin_login";
GRANT brerc_notifier TO :"notifier_login"
WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
COMMIT;
```

Apply an equally reviewed `REVOKE CONNECT ... FROM PUBLIC` plus explicit
legitimate-role grants to each *other* `datallowconn` database. Capture the
pre-change `pg_database.datacl`, memberships and HBA revision in the controlled
change record. Rollback means restoring that captured ACL/HBA state—not blindly
granting defaults—then revoking `brerc_notifier` and the publication-database
`CONNECT` from the notifier login. Confirm API, loader, backup and recovery-admin
connections before ending the maintenance window.

### Controlled dead-letter redrive

Separation of duties is intentional. `brerc_monitor` can see the opaque
notification UUID in `serve.etl_notification_delivery_event`, while the
break-glass operator can execute the redrive function but cannot browse that
view. When a dead-letter alert fires:

1. an authorised monitor records the UUID and fixed failure code in the
   controlled incident system and hands only the UUID to the approved operator;
2. an independent reviewer confirms the destination/provider remediation and
   selects one allowed reason code;
3. the operator uses a dedicated login whose only membership is provisioned as
   `GRANT brerc_notifier_operator TO <operator_login> WITH ADMIN FALSE, INHERIT
   TRUE, SET FALSE`, then calls
   `loader_control.requeue_dead_notification(uuid, reason_code)` through a
   parameterised/interactive client; and
4. the monitor verifies the `REDRIVEN` event and subsequent fixed delivery
   state. Revoke temporary break-glass credentials after the incident.

Do not grant the UUID-bearing monitor view to the operator merely for
convenience, do not place UUIDs in public GitHub issues, and never query the raw
outbox. Production acceptance must separately prove the operator login's
attributes, exact membership options and forbidden accesses; the worker's
automatic preflight checks only its own service login.

## Starting and checking the service

The syntax-only overlay check is runnable now and needs no secrets:

```sh
docker compose -f deploy/notifier.compose.yaml \
  config --no-interpolate --quiet
```

The following deployment commands become runnable only after issue #40
supplies the publication store/migrations, the reviewed production base Compose
file exists, and the immutable worker image digest has been approved:

```sh
docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/notifier.compose.yaml \
  config --quiet

docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/notifier.compose.yaml \
  up --no-build -d notifier

docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/notifier.compose.yaml \
  ps notifier

docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/notifier.compose.yaml \
  exec notifier python -m brerc_notifier validate \
  --config /run/secrets/notifier-config

docker compose \
  -f deploy/docker-compose.yml \
  -f deploy/notifier.compose.yaml \
  exec notifier python -m brerc_notifier probe \
  --config /run/secrets/notifier-config
```

`once` claims and may send real queued notifications; it is not a harmless
health command. Use it only in the controlled acceptance procedure. `run` is
the normal long-lived process supplied by the image.

Do not copy the root `docker-compose.yml` into production. It is the legacy
sample-data stack and contains development fallbacks. The production compose
and this overlay must be reviewed together after the store port lands.

The notifier's `/live`, `/ready` and `/metrics` endpoints are reachable only by
authorised monitoring on the private container network. `/ready` must fail when
configuration is invalid, the database cannot be verified or the last
successful poll is stale. A dead letter is exposed as a metric/alert; it does
not make readiness fail, because restarting a healthy worker cannot repair a
recipient or provider configuration problem.

The long-lived process also performs a periodic no-send provider preflight even
when the outbox is empty. Alert when
`brerc_notifier_provider_preflight_ok` is `0` or
`brerc_notifier_provider_preflight_failures_total` increases. For SMTP this
checks verified implicit TLS, authentication and `NOOP`; for a webhook it checks
verified TCP/TLS only, not the HTTP path/authentication or human receipt. A
provider failure does not deliberately trigger a container restart loop.

The independent monitoring agent may join that private network or consume the
container runtime's health state and scrape through an authenticated local
collector. Do not publish `9108` on the host or add a public Caddy route merely
to make an external SaaS probe convenient.

## Required automated evidence

The notifier CI gate must remain mandatory alongside the complete API and ETL
suites. It must prove:

- production config rejects plaintext/unverified database and SMTP connections,
  inline/absent secrets, unknown aliases, header injection and unsafe defaults;
- two workers cannot deliver the same active lease;
- a stale lease can be recovered but an old lease token cannot acknowledge it;
- success and failure events produce only the documented fixed-field message;
- no address, source data, coordinate, exception/provider text or credential is
  written to the database, metrics or logs;
- provider failures use fixed codes, exponential backoff and a bounded
  dead-letter transition;
- the notifier role cannot select private/base tables, insert events, directly
  update delivery state, perform DDL or `SET ROLE` to a stronger capability;
- configuration selects only hostname-verified database TLS, implicit SMTP TLS
  or HTTPS and maps certificate/hostname failures to fixed fail-closed results;
- the container runs non-root, read-only, without Linux capabilities or a
  published port; and
- the compose overlay renders only when every required controlled file is
  supplied.

CI provider acceptance uses offline test doubles. It proves fixed payloads,
verified-context selection, classification, lease renewal and no-send preflight
behaviour, not a real TLS peer or delivery to a human inbox. Real wrong-CA,
wrong-hostname and plaintext negative tests remain part of controlled production
acceptance. Before #40 lands, the migration checks
on this branch are static contract tests because migration 0001 is deliberately
absent from protected `main`. After #40 supplies migration 0001 and its real
PostGIS fixture, CI must execute 0002 and the concurrent
claim/lease/ack/retry/privilege cases against PostgreSQL 16. Static SQL checks
must not be reported as database integration evidence.

## Production acceptance procedure

Run this only inside the approved environment against the exact protected-main
SHA and immutable image digest.

1. Record the revision, image digest, migration digest and configuration digest
   in the controlled evidence store. Record identities by internal reference,
   not address, in transferable evidence.
2. Prove the notifier login's attributes and direct membership. Prove all
   forbidden SELECT/UPDATE/DDL/role-escalation operations fail.
3. Prove database `verify-full` succeeds and wrong-CA, wrong-hostname and
   plaintext tests fail. Repeat for the SMTP TLS identity.
4. Run `validate` for the strict configuration and `probe` for database TLS,
   identity, migration and metrics access. `probe` also performs a no-send
   provider check: SMTP establishes verified implicit TLS, authenticates and
   sends `NOOP`; HTTPS establishes verified TCP/TLS without making an HTTP
   request. This proves configuration and connectivity, not human receipt. Any
   unknown destination alias or unavailable dead-man monitor blocks activation.
5. In an isolated acceptance destination, create genuine terminal success and
   failure events through the reviewed loader/database interfaces—not with a
   manual table INSERT or a notifier-only canary command. Prove the worker
   delivers each and the database reaches `delivered` with the expected attempt
   count. The named recipient must acknowledge each notification ID and UTC
   receipt through the controlled evidence route; provider acceptance alone is
   insufficient.
6. Prove retry, dead-letter and stale-lease recovery using synthetic events in
   that isolated target. Never deliberately fail the public production release.
7. Stop the worker and prove the independent monitor alerts the operational
   owner. Restore it and prove recovery. Separately prove public HTTPS,
   certificate-expiry, database, disk/WAL and backup-age/failure alerts.
8. Inspect the restricted logs, messages and metrics for forbidden fields.
   Retain only fixed-code, aggregate or opaque-ID evidence approved for transfer.
9. Obtain the named service owner, incident owner and recipient sign-off; then
    rotate/revoke temporary acceptance credentials.

### Minimum retained receipt

Retain, in BRERC's controlled evidence store:

- exact protected-main SHA and immutable container/migration/config digests;
- UTC test window and environment reference;
- opaque notification IDs and event types;
- fixed database delivery states, attempt counts and fixed failure codes;
- TLS positive/negative verdicts without private infrastructure details;
- recipient acknowledgement references;
- dead-man and escalation acknowledgement references; and
- operator, independent reviewer and service-owner acceptance references.

Never retain recipient addresses, provider response bodies, DSNs, credentials,
internal hosts/CIDRs, source rows, exact locations or raw exceptions in GitHub.

## Operational alert catalogue

The named owner must approve actual thresholds and response targets. The minimum
coverage is:

| Condition | Detection source | Required response |
| --- | --- | --- |
| Public page/API unavailable | Independent external HTTPS probe | Alert the service/incident owner through a channel independent of the dashboard host. |
| TLS certificate approaching expiry | Independent certificate probe | Alert before the approved renewal margin and verify Caddy/provider renewal. |
| Database unavailable or resource pressure | Provider/PostgreSQL monitoring | Alert on health, connections/locks, disk and WAL thresholds. |
| Backup late/failed or restore unproven | Backup platform | Alert independently; execute the approved restore-drill process. |
| ETL terminal failure | Transactional outbox worker | Send the fixed failure code and opaque notification/job IDs. |
| Notification backlog or dead letter | Private worker metrics/database status | Alert through the independent channel; never rely only on the failing mail path. |
| Provider preflight fails | Private `brerc_notifier_provider_preflight_ok` gauge and `brerc_notifier_provider_preflight_failures_total` counter | Check approved egress, TLS identity and credentials; alert independently and do not restart-loop the worker. |
| Worker stopped or stale | Independent dead-man/container monitor | Alert the operational owner and follow the restart/escalation runbook. |

## What remains human/external

Repository work cannot supply or prove the following:

1. the final production host/private network/database/TLS/backup platform;
2. a named service owner, incident owner, post-handover operator, recipients,
   escalation channel, thresholds and response targets;
3. SMTP/provider approval, account/credential, firewall egress and sender-domain
   SPF/DKIM/DMARC configuration;
4. an independent monitoring/dead-man service and its separate alert channel;
5. deployment of the exact protected-main image and migrations to BRERC's host;
6. receipt acknowledgements from the real named recipients; and
7. retained production acceptance and handover sign-off.

Until those seven items and the automated gates pass, the honest state is
**implemented and synthetically verified, production acceptance pending**.
