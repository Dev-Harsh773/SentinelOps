# SentinelOps single-node deployment

Stage 24 runs one Python process with one attached persistent volume. HTTPS
terminates at the hosting provider; requests reach the backend directly.
There is no production validation gateway, tunnel, queue service or second worker.
This is a deployment candidate, not a claim that hosted validation has passed.

## Local development and Docker

Local development retains `python -m app.cli` on loopback without a token.
Install the runtime lock plus test/client dependencies as needed. Local `.env`
files are ignored by Git. Never use anonymous development mode on a public host.

Set `SENTINELOPS_OPERATOR_TOKEN` privately in the terminal environment to a
random value with at least 32 characters. Do not put it on the command line,
in source, screenshots or chat. Then run:

```powershell
docker build -t sentinelops:stage24 .
docker compose up -d --build
curl.exe http://127.0.0.1:8024/live
curl.exe http://127.0.0.1:8024/ready
docker compose logs --tail 30
```

Compose binds only loopback and preserves `sentinelops-data`. `docker compose
down` preserves it; **do not use `down -v` on data you need**. Bind mounts must
be writable by UID/GID 10001. The image excludes local databases, .env, Git,
workspaces, tests, Android and desktop. Python runtime dependencies are exact
versions; the base image is pinned by digest. Debian security packages are
resolved at build time, so builds are not byte-for-byte reproducible.

Run the reproducible container gate with `python -m
tools.stage24_container_validation`. It uses port 8024, removes its own container,
and preserves a uniquely named validation volume. Its JSON result contains no
credentials. Docker administrators can inspect container environment variables;
treat Docker host access as privileged.

## Production configuration

| Variable | Requirement/default |
|---|---|
| `APP_ENV` | `production` (also hardens `staging`) |
| `HOST`, `PORT` | `0.0.0.0`, provider port or 8000 |
| `RUNTIME_DIR` | Absolute mounted path, outside packaged source; image `/var/lib/sentinelops` |
| `SENTINELOPS_OPERATOR_TOKEN` | Required private random bearer token, minimum 32 characters |
| `SENTINEL_WORKSPACES_ROOT` | Defaults to `RUNTIME_DIR/workspaces`; stays inside volume |
| `WATCHER_DB_PATH`, `PROJECT_DB_PATH` | Omit; production overrides must equal `RUNTIME_DIR/sentinelops.db` |
| `WATCHER_ENABLED` | Image false; disables synthetic local collectors, not external ingestion/detection |
| `PUBLIC_INGRESS_URL` | Optional stable HTTPS origin, no path/query/credentials |
| `CORS_ALLOWED_ORIGINS` | Empty by default; comma-separated exact HTTP(S) origins if needed |
| `MAX_REQUEST_BODY_SIZE` | 10485760 bytes; configurable up to 16 MiB |
| `RATE_LIMIT_INGEST_PER_MINUTE` | 300 per socket peer |
| `RATE_LIMIT_AUTH_PER_MINUTE` | 30 failed operator authentications per socket peer |
| `RATE_LIMIT_EXPENSIVE_PER_MINUTE` | 10 protected expensive POST operations per socket peer |
| `RATE_LIMIT_MAX_KEYS` | 4096 bounded in-memory counters |
| `LOG_JSON` | Image true; production always uses safe JSON formatting |
| `LLM_PROVIDER` | `mock` requires no AI credentials; configure real provider separately |

Notification retry/lease settings remain those documented in `.env.example`.
Production requires the notification worker enabled. Do not run multiple workers:
the OS volume lock rejects a second production process. Limits reset on restart.
Forwarded IP headers are not trusted: a reverse proxy may cause clients to share
a limit bucket. Tune for aggregate legitimate traffic and use provider edge
protection where needed. Limits do not replace protection from slow connections.

## Render deployment (requires user account and spending approval)

`render.yaml` defines one Docker web service, the smallest listed paid compute
plan, and a 1 GB disk. Automatic deployments are off. Review current pricing in
the Render account before importing it. Free Render web services cannot satisfy
this design's persistent-disk requirement. Only data under the disk mount is
durable, and disk-backed redeploys have downtime. See [Render disks](https://render.com/docs/disks)
and the [Blueprint reference](https://render.com/docs/blueprint-spec).

1. Review, commit and push the candidate yourself; the agent does not push.
2. After approving paid infrastructure, import the Blueprint or configure an
   equivalent existing service. Enter the operator token privately in Render.
3. Verify the mounted path is writable as UID 10001. If the provider mount is
   root-owned, provision its ownership through the provider's supported admin
   mechanism before starting the non-root application; never fall back to
   ephemeral storage. This provider-specific gate remains unverified locally.
4. Check `/live` and `/ready` over the assigned stable HTTPS URL. Set
   `PUBLIC_INGRESS_URL` to that origin. Do not use a Quick Tunnel.
5. Onboard the monitored repository into the managed workspace and create a
   webhook connector with its own secret. Configure chaos-demo telemetry to
   `https://<stable-host>/connectors/<connector-id>/ingest` with the configured
   connector secret header. Do not put a secret in a URL.
6. Perform the hosted failure/recovery and restart matrix in Stage 24 verification
   before approving the stage. The 512 MB plan has not been capacity-tested;
   check indexing/LLM memory use before increasing workload.

## Authentication and clients

Only GET `/health`, `/live`, `/ready` are anonymous operational endpoints.
POST `/connectors/{id}/ingest` uses connector-specific authentication. All other
routes, including API documentation, require `Authorization: Bearer <operator-token>`
when a token is configured. A production connector without a secret is rejected.
Use different secrets for operators and connectors. This is one trusted operator
role, not multi-user authorization; project isolation remains domain-enforced.

Desktop: set `SENTINELOPS_API_URL` to the HTTPS origin and
`SENTINELOPS_OPERATOR_TOKEN` privately before launching `python -m desktop.main`.
The token is not persisted to desktop JSON. Restart after rotation. Cleartext
token transmission is permitted only to loopback.

Android: Settings accepts the HTTPS server URL and masked operator token. Blank
token input keeps the saved value; Clear saved token removes it. AES-GCM ciphertext
is stored in private preferences using an Android Keystore key; app backup is
disabled. Token use applies to foreground calls and WorkManager polling.
Connection testing probes public health; authenticated data screens must also be
checked. WorkManager remains best-effort polling, not real-time push. Device
Keystore persistence needs a physical-device/emulator check beyond JVM tests.

## Storage, readiness, restart and recovery

Every durable domain uses `RUNTIME_DIR/sentinelops.db`. Existing additive schema
initializers run before workers and readiness; startup never clears application
tables. Managed clones and source files live beside the database on the volume.
Source indexes are reconstructed in memory from persisted workspace/configuration.

`/health` and `/live` mean the process responds. `/ready` requires completed
startup, a live notification poller, and an accessible writable SQLite database.
Busy/unavailable SQLite returns 503. A monitored application's failure does not
make SentinelOps unready. Shutdown stops workers and closes connections; startup
recovers durable delivery claims and aborts orphaned SafeAction execution claims
according to existing audit rules. A failed volume/path configuration fails startup.

Rotate operator tokens by setting a new secret in the host environment and
restarting, then updating desktop/Android. Old tokens cease working immediately;
there is no overlapping-key period. Rotate a connector's `auth_secret` through
its authenticated update API and update the producer together; expect a short
ingestion interruption. Never reuse the operator token as a connector secret.

## Backup and isolated restore

SQLite online backup includes committed WAL state and validates integrity. Choose
a new timestamped destination; existing destinations are always refused:

```sh
python -m app.backup backup /var/lib/sentinelops/sentinelops.db /var/lib/sentinelops/backup-20261018T120000Z.db
python -m app.backup restore /var/lib/sentinelops/backup-20261018T120000Z.db /var/lib/sentinelops/restore-test.db
```

Run inside the container/provider shell. The parent destination directory must
exist. Keep backup copies encrypted off-host; a backup on the same volume alone
does not protect against volume loss. Database backups contain connector and
notification credentials and must be treated as secrets.

The command restores the database only. Also archive the managed workspaces while
repository mutations are stopped. To recover a service, stop it, restore into a
new isolated runtime directory, copy workspaces, preserve their configured paths,
validate records, and deliberately switch the mount/configuration. Do not overwrite
a running SQLite database or copy only its main file while it is active. Test
recovery with outbound destinations disabled/isolated to avoid duplicate delivery.

CI validates Python, desktop, gateway, Android and container behavior; it never
deploys production. Chaos-demo tests run separately in its own repository.
