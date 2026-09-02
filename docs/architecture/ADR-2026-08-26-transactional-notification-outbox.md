# ADR: deliver ETL notifications from a transactional outbox

- **Date:** 26 August 2026
- **Status:** Proposed for review; production acceptance pending
- **Decision owners:** database/ETL and production service owners
- **Depends on:** the publication store and atomic loader tracked by GitHub issue #40

## Context

The publication loader must report terminal success or failure, but sending a
notification inside the loader transaction is unsafe. The provider could accept it and
the database transaction could then roll back, or the release could commit and
the provider operation could fail. Retrying either operation can also create a
duplicate release or duplicate message.

The publication-store design already resolves the first half of this problem:
the same transaction that records a terminal job state inserts one fixed-field
row in `loader_control.notification_outbox`. That row contains opaque IDs,
fixed event/failure codes and a destination alias. It contains no recipient
address, exception text, source row, coordinate or credential.

The current protected `main` does not yet contain that store. It remains in the
authorship-preserving port queue under issue #40. Consequently, this worker can
be implemented and tested now, but it cannot be deployed or truthfully called
operational until #40 and the production database gate (#46) are complete.

## Decision

Use a separate, least-privilege notification worker to drain the transactional
outbox after the loader transaction commits.

1. The loader only creates outbox rows. It cannot mark them delivered.
2. A dedicated `brerc_notifier` database capability may call only reviewed
   claim/acknowledge/retry functions. It receives no direct table privileges.
3. Claims use row locks with `SKIP LOCKED` and an expiring, unguessable lease
   token. A later worker cannot acknowledge an earlier worker's lease.
4. The worker commits the claim before contacting the delivery provider. It never
   holds a database lock while making a network request. A bounded background
   operation renews the exact active UUID/token lease during provider I/O;
   acknowledgement remains token-bound if renewal or ownership is lost.
5. Retry delays and the terminal dead-letter transition are database-owned.
   The worker submits only a fixed delivery-result code, never provider text.
6. Recipient addresses and provider credentials are resolved from controlled
   deployment configuration using the row's `destination_key`. They are never
   stored in the publication database or repository.
7. Production permits only hostname-verified database TLS and either verified
   SMTP TLS or an approved HTTPS webhook. Plaintext transports are absent.
8. Email and webhook content is fixed-field: event type, opaque notification
   and job IDs, optional opaque release ID, fixed failure code and UTC time. It
   contains no counts, source values or arbitrary exception/provider messages.
9. The deterministic RFC Message-ID or webhook Idempotency-Key includes
   `notification_id`. Delivery is
   nevertheless **at least once**: a process can stop after the provider accepts
   a message but before the database acknowledgement commits. Operators and
   recipients must treat the notification ID as the deduplication key.
10. Worker liveness, readiness and fixed-label metrics are exposed only on the
    private container network. Caddy must not proxy or publish them.
11. The long-lived worker performs periodic no-send provider preflight even
    when the outbox is empty. Provider reachability is an alert signal, not a
    restart condition and not proof that a human received a notification.
12. Production runs a reviewed image by immutable digest on separate private
    database and control networks. It does not build on the production host.

## Monitoring boundary

The worker reports its own health and outbox condition. It cannot independently
prove that its host, network, mail provider or the public dashboard is reachable:
a component cannot reliably monitor the failure domain it shares. Production
therefore also requires an independently operated monitor for public HTTPS,
certificate expiry, host/container health, database health, backup age/failure
and the notifier dead-man signal. That monitor and its escalation channel are
chosen by BRERC/Bristol City Council under issue #46.

No access-log or metric label may contain an address, destination alias, source
identifier, species, grid reference, release/job/notification ID, provider
response or exception text. Opaque IDs may appear only in the restricted
worker's fixed-code operational log and retained controlled evidence.

## Rejected alternatives

- **Send inside the loader transaction:** couples external I/O to atomic
  publication and cannot make the database/provider outcome consistent.
- **Let the loader send after commit:** a crash between commit and send loses
  the notification, and expanding the loader's network/secrets surface weakens
  separation of duties.
- **Poll the ETL run-history SQLite file:** that file is host-local UI state,
  not the authoritative publication-store transaction and cannot safely drive
  production delivery.
- **Give the worker direct UPDATE on the outbox:** permits it to rewrite event
  truth or acknowledge another process's delivery.
- **Expose worker metrics through public Caddy:** creates an unnecessary public
  operational surface and risks metadata leakage.

## Consequences

The design provides durable, concurrency-safe, bounded-retry delivery without
placing recipient details in the database. It also makes the honest remaining
boundary explicit: code and synthetic tests do not prove production delivery.
A named recipient must acknowledge a controlled message from the exact deployed
revision, and an independent dead-man alert must be demonstrated before the
production gate is complete.
