# Stage 24 verification - 2026-10-18

**Status: PENDING VERIFICATION.** Local implementation and Docker validation passed.
The user explicitly chose to keep hosting pending until Git review. No paid
resource was created, no deployment was published, and neither repository was
committed or pushed. Stage 25 was not started.

## Architecture and hosted environment

One non-root Docker application process, one persistent volume, one SQLite
database for all durable domains, managed source workspaces on the same volume,
and in-process connector/notification workers. Docker uses Python 3.12, exact
runtime dependency versions, a digest-pinned base image, configurable PORT, and
UID/GID 10001. Render configuration declares one paid Docker web service and
one 1 GB disk at `/var/lib/sentinelops`; deployment is manual.

No stable hosted SentinelOps URL exists from this stage's work. Provider disk
ownership, provider restart/redeploy, and HTTPS ingress remain unverified.
The local Docker volume passed restart/replacement tests; this does not establish
Render behavior. No Cloudflare tunnel participated in the container validation.

## Automated regression results

| Repository/suite | Exact command | Result |
|---|---|---|
| SentinelOps backend | `python -m pytest tests --ignore=tests/desktop -q` | **511 passed**, 104.05 s |
| Desktop | `python -m pytest tests/desktop -q` | **84 passed**, 9.12 s |
| Gateway | `python -m pytest tools/validation_gateway/test_gateway.py -q` | **9 passed**, 3.26 s |
| Android, from `android` with JDK 17 | `.\gradlew.bat testDebugUnitTest --rerun-tasks` | **35 tests**, 0 failures, 0 errors; BUILD SUCCESSFUL |
| Chaos demo, `D:\SentinelOpsChaosDemo` | `python -m pytest tests -q` | **19 passed**, 2.73 s |
| Whitespace | `git diff --check` | Passed |

New focused coverage: production config rejection; shared DB path; startup with a
new and existing schema; repeated initialization; worker lifecycle; database
unavailability/readiness; single-process lock; online WAL backup and isolated
restore/no-overwrite; route authentication boundaries; streaming body cap; narrow
CORS; bounded deterministic limiter; workspace traversal; log redaction; desktop
headers/401/HTTPS; Android token supplier/rotation/HTTPS/no redirects. Existing
Stage 23 recovery and notification tests remain in the full backend suite.

CI was added for Python/desktop/gateway, Android JVM and Docker build/validation.
The workflow itself has not run on GitHub because these changes are unpushed.
Chaos-demo CI remains outside this repository; its suite was run locally.

## Actual Docker and production-mode validation

Commands: `docker build -t sentinelops:stage24 .` and
`python -m tools.stage24_container_validation`. Both exited 0 on the final run.
Docker Desktop's Linux engine was used. The harness publishes only loopback port
8024, generates private temporary credentials in memory, and preserves a uniquely
named evidence volume after removing its own container.

The final harness and supplemental image checks established:

1. Production startup as UID 10001; Docker HEALTHCHECK healthy; `/live` and `/ready` 200.
2. Missing production operator token fails startup; image scan finds no `.env`,
   runtime DB files or Git metadata in packaged application source.
3. Protected APIs reject absent/invalid/connector credentials and accept the
   operator bearer. Ingress accepts its connector secret without the operator
   token, and rejects an operator bearer alone.
4. A 65,537-byte body against a 65,536-byte validation cap returns 413; malformed
   JSON returns the existing 422 contract. A test additionally checks chunked
   overflow before any downstream route runs.
5. Direct authenticated connector telemetry persists and creates a HIGH incident.
   Evidence is retained; a mock-provider investigation and remediation reference
   `create_order` from the managed source workspace. Historical memory is created.
6. A controlled in-container HTTP receiver returns 503 on its first delivery and
   200 on its second. Durable notification attempt history records both attempts.
   This is automatic bounded delivery, not a manually approved retry action.
7. A SafeAction proposal and audit record are persisted in **pending approval**.
   The harness does not approve or execute it.
8. The real desktop HTTP client reads authenticated project, connector, evidence,
   investigation, remediation, memory, notification/attempt and action/audit data.
9. `docker restart` preserves those representative records. Removing and replacing
   the container with the same named volume preserves them again.
10. Live SQLite backup passes integrity validation. Isolated restore passes
    integrity validation and every table's row count matches the live database.
    The live database is never overwritten.
11. Operator token, connector secret and private destination path are absent from
    captured container stdout. Production access logs are disabled; application
    JSON logs redact configured credentials, bearer strings and URLs.

Evidence is local and ignored: `runtime/stage24-container-results.json`,
`runtime/stage24-container-final.log`, `runtime/stage24-docker-build-final.log`,
`runtime/stage24-backend-final.log`, desktop/gateway logs, and Android XML results.
The JSON records the final retained volume name. Earlier failed harness attempts
left separate evidence volumes; none is the operator's live database. Do not use
global Docker pruning to remove validation evidence or unrelated user data.

Final image ID: `sha256:a15cbd869e39f63031ea44158612387b011be75fed3690919b52e05eaf693ec9`.
Final evidence volume: `sentinelops-stage24-03c55a8543-data`; all 12 harness checks passed.

The harness initially expected malformed JSON 400 instead of the existing 422,
omitted the log signal type, and used `incident_id` instead of the API's `id`.
Those harness assumptions were corrected. A receiver-start race caused an extra
network retry; waiting for its listening socket made the controlled 503/200 test
deterministic. No application behavior was weakened to make those checks pass.

## Security and operational limits

Central bearer authentication protects all routes except GET health/live/ready
and connector-authenticated POST ingress. Empty production connector secrets
cannot ingest. CORS is off unless exact origins are configured. Rate limits are
bounded in-process per socket peer; trusted-proxy headers do not bypass them.
Proxies can aggregate clients into one bucket; restart clears counters. One
operator role is supported, not an enterprise identity/authorization system.

Every store shares the configured production database. Additive constructors run
before workers/readiness. Production workspace registration and indexing reject
escape from the managed root, and dot/dot-dot project IDs are rejected. Existing
clear safeguards also protect the configured database path. A volume lock prevents
two production processes from recovering the same durable work concurrently.

Backup covers SQLite, not workspace archives; the deployment guide describes
coordinated workspace copying and off-host encrypted storage. Persistent databases
contain connector/delivery credentials. Docker host administrators can inspect
container environment variables. Debian security package versions are resolved at
build time. The smallest Render compute plan is not a capacity benchmark.

Desktop token storage is environment-only. Android uses Keystore-backed AES-GCM
storage and disables app backup. Android settings test public health; validate
authenticated data screens as well. JVM tests do not validate device Keystore
behavior. No hosted desktop GUI or physical Android session was claimed.

## Remaining acceptance gates

- User Git review/commit/push and hosting authorization; approved persistent HTTPS target.
- Provider volume permissions, stable `/ready`, and hosted operator/connector auth matrix.
- Real hosted chaos baseline (health 200/order 201), controlled order 500, direct
  HTTPS telemetry, incident/evidence, source-grounded investigation/remediation,
  notification delivery, then recovery to health 200/order 201.
- Hosted restart/redeploy persistence across the representative domain records.
- Hosted desktop visual check and Android/device authentication/alert check.

The local source fixture and controlled webhook receiver are production-mode
component validation; they are not the real hosted chaos-demo end-to-end gate.
Stage 24 therefore remains pending, not approved as production-ready.

## Files changed

| File | Change |
|---|---|
| `.env.example` | Production storage/auth/CORS/limit/log settings without credentials |
| `.gitignore` | Environment variants, Stage 24 evidence and SQLite exclusions |
| `.dockerignore` | Allowlisted production build context |
| `Dockerfile` | Pinned base, locked Python dependencies, non-root single-worker server/healthcheck |
| `requirements-production.lock` | 45 exact runtime dependency versions |
| `compose.yaml` | Loopback local container and persistent named volume |
| `render.yaml` | Manual paid single-node deployment candidate and disk |
| `.github/workflows/validation.yml` | Python, desktop, gateway, Android and Docker gates; no deploy |
| `app/serve.py` | Environment-based single-worker container entry point |
| `app/cli.py` | Revalidated environment and safe non-local bind/reload behavior |
| `app/main.py` | Storage-first lifecycle, readiness state, worker cleanup, central middleware, safe production errors |
| `app/api/health.py` | Liveness alias and database/worker readiness |
| `app/common/config.py` | Production validation, canonical storage, auth and network limits |
| `app/common/access.py` | Central bearer boundary and bounded rate limiter |
| `app/common/instance_lock.py` | OS-held production-volume ownership |
| `app/common/storage.py` | Initialize every durable domain before readiness |
| `app/common/middleware.py` | Bounded streaming request accumulation before routes |
| `app/common/logging.py` | Safe structured production formatter |
| `app/backup.py` | Validated online SQLite backup and isolated no-overwrite restore |
| `app/actions/dependencies.py` | Configured shared DB path |
| `app/agents/dependencies.py` | Configured shared DB path |
| `app/agents/repository.py` | Configured production clear guard |
| `app/connectors/dependencies.py` | Configured shared DB path |
| `app/connectors/auth.py` | Production secret requirement and byte-safe constant-time comparison |
| `app/connectors/routes.py` | Generic malformed telemetry errors |
| `app/incidents/dependencies.py` | Configured shared DB path |
| `app/incidents/repository.py` | Configured production clear guard |
| `app/knowledge/service.py` | Revalidate production source workspace before scanning |
| `app/memory/dependencies.py` | Configured shared DB path |
| `app/memory/repository.py` | Configured production clear guard |
| `app/notifications/dependencies.py` | Configured shared DB path |
| `app/notifications/delivery.py` | Worker health checks actual poller task |
| `app/projects/schemas.py` | Reject dot/dot-dot and path traversal IDs |
| `app/projects/service.py` | Managed-root production registration/clone checks |
| `app/remediation/dependencies.py` | Shared paths for proposals, reviews and branches |
| `app/remediation/repository.py` | Configured production clear guard |
| `app/remediation/review_repository.py` | Configured production clear guard |
| `app/remediation/branch_repository.py` | Configured production clear guard |
| `app/telemetry/dependencies.py` | Configured shared DB path |
| `app/telemetry/repository.py` | Configured production clear guard |
| `desktop/api/client.py` | Bearer environment/argument support, HTTPS guard, safe 401, no redirects |
| `android/app/src/main/AndroidManifest.xml` | Disable backup of application credential-related state |
| `android/.../data/local/AppPreferences.java` | Secure token accessors |
| `android/.../data/local/OperatorTokenStore.java` | Android Keystore/AES-GCM token persistence |
| `android/.../data/remote/ApiClientFactory.java` | Dynamic bearer provider, HTTPS guard, no transport logging/redirects |
| `android/.../di/ServiceLocator.java` | Token provider wired into foreground client |
| `android/.../workers/IncidentPollingWorker.java` | Token provider wired into background polling |
| `android/.../ui/settings/SettingsViewModel.java` | Save/clear token and safe configuration error |
| `android/.../ui/settings/SettingsFragment.java` | Masked token input behavior |
| `android/app/src/main/res/layout/fragment_settings.xml` | Minimal token input/clear control |
| `android/.../data/remote/OperatorAuthenticationTest.java` | Three JVM client-auth tests (under test source tree) |
| `tests/test_production.py` | 24 focused backend operational/security cases |
| `tests/desktop/test_operator_auth.py` | Three desktop authentication cases |
| `tools/stage24_container_validation.py` | Reproducible real-container operational/persistence gate |
| `docs/DEPLOYMENT.md` | Deployment, configuration, client auth, backup, rotation and limits |
| `docs/STAGE24_VERIFICATION.md` | This evidence and remaining-gates report |
| `docs/PROJECT_JOURNAL.md` | Stage 24 implementation/validation entry |
| `project.md` | Current status and corrected committed Stage 23 baseline |

Android abbreviated Java paths start at
`android/app/src/main/java/com/sentinelops/mobile/`; the authentication test starts
at `android/app/src/test/java/com/sentinelops/mobile/`.

## Git handoff

Baseline/HEAD remains `1d7be35d5ec7c45666681f67f73ac9edf52e6bf1` on `main`.
Stage 24 changes are unstaged and uncommitted. Chaos-demo working tree is clean.
Final inventory: 40 modified tracked files and 18 new files (58 total), zero staged
files. Tracked diff: 418 insertions and 104 deletions; new artifacts are listed above.
Nothing was committed or pushed. Suggested commit after review:
`Implement Stage 24 single-node deployment and operational hardening`.
