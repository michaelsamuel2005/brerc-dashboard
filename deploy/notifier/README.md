# Notifier deployment inputs

This directory contains syntax-only, non-secret examples. The real files stay
outside the repository in BRERC/Bristol City Council's approved secret store.

The compose overlay mounts six controlled files:

1. a strict notifier YAML built from
   [`../../api/notifier.configuration.example.yaml`](../../api/notifier.configuration.example.yaml);
2. a libpq service file built from `postgres-service.example.conf`;
3. a libpq passfile containing exactly the notifier login credential;
4. the approved PostgreSQL CA certificate;
5. the SMTP username; and
6. the SMTP password.

It also requires an approved image repository plus `sha256:` digest and two
pre-created external network names: a database-only network and a notifier
control/monitoring network. Production uses `up --no-build`; building on the
host or deploying a moving tag is not an accepted release path. Restrict host
egress from the control network to the one approved delivery endpoint. Neither
network is public, Caddy must join neither, and only the database, notifier and
authorised collector may join them. Because the health server binds inside the
notifier container, an explicitly joined peer on either private network can
reach it; the absence of a host `ports:` mapping is the public boundary.

This is the recommended SMTP profile. The application also supports the strict
HTTPS-webhook shape documented in the notifier configuration template. A
webhook deployment needs its own reviewed overlay that mounts only
`BRERC_NOTIFIER_WEBHOOK_SECRET_FILE`; never use placeholder SMTP secrets.

The image runs as numeric UID/GID `65532:65532`. A secrets platform must mount
each file for that identity at mode `0400`. Docker Compose implements local
file-backed secrets as bind mounts and may not apply the overlay's `uid`, `gid`
or `mode`; in that deployment mode, provision the host files as `65532:65532`
and `0400` in a root-controlled directory, then verify the effective ownership
inside the container before startup. Never make them world-readable merely to
make a failed mount work. The service file must contain no password. The
passfile must use libpq's `host:port:database:user:password`
format and must not be pasted into a shell command, `.env`, GitHub, email or
chat. The service file is deliberately strict: it must contain exactly the one
configured section and the five keys shown in the example (`host`, `port`,
`dbname`, `user`, `sslmode`). Its database/login must match the notifier YAML,
`sslmode` must be `verify-full`, and a `password` or second service section is
rejected. This keeps the separate passfile as the only database-password input.

The SMTP username/password and webhook-secret files are exact values: do not
append a trailing newline. The strict parser rejects newline-delimited secrets
rather than silently changing a credential. Use the approved secret tool's
binary/exact-value facility, not `echo`.

The notifier configuration template names the six environment variables supplied by
the overlay; it does not contain a credential. Recipient addresses do occur in
the real notifier YAML, so that file is controlled even though an address is
not an authentication secret.

The PostgreSQL preflight also requires a deliberately narrow cluster posture,
not merely table grants. Before deployment, a DBA must preserve all legitimate
API/loader/backup/admin access while removing `PUBLIC TEMPORARY` from the
publication database, removing unwanted `PUBLIC CONNECT` across connectable
databases, granting the notifier login direct `CONNECT` only to the publication
database, and restricting the same login/database/source in `pg_hba.conf` over
TLS. Grant its PostgreSQL 16 membership exactly with `ADMIN FALSE, INHERIT TRUE,
SET FALSE`. The reviewed procedure and warnings are in the main runbook.

For the complete procedure and honest acceptance boundary, see
[`../../docs/NOTIFICATION_WORKER.md`](../../docs/NOTIFICATION_WORKER.md).
