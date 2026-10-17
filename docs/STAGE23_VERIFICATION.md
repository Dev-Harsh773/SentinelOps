# Stage 23 verification: durable alert delivery

Review date: 2026-10-18 (Asia/Calcutta).

## Status: APPROVED

Implementation, automated regression gates and live desktop inspection passed.
Baseline: `27b98054d8d91a67bd995f7e3d493fd959df3b36`, initially clean and synchronized
with `origin/main`. No commits or pushes are authorized. Stage 24 is out of scope.

## Architecture and compatibility

Incident create/update and notification intent now commit in one SQLite transaction.
`notification_outbox` holds the incident event and enabled subscription snapshots.
The immediate listener and background replay use that snapshot. If the process dies
between incident commit and notification fan-out, replay resumes on startup. A failed
outbox write rolls back the incident write rather than reporting a partially durable event.

Each destination is persisted before dispatch. Replay acknowledges an intent only after
all eligible destination records are durable; partial fan-out is safe to replay through
unique dedup keys. Completed outbox rows retain event identity but discard subscription
configuration snapshots. The original notification retains its immutable delivery configuration.
Changing or deleting a subscription does not rewrite an already-committed delivery intent.

Existing severity thresholds and channels (`webhook`, `local_feed`) are retained.
Local-feed insertion is itself delivery and does not create fictitious HTTP attempts.
No new providers, distributed queue, or autonomous remediation were introduced.
The production incident and notification repositories must share the same SQLite database,
as they do in the standard dependency configuration. In-memory incident repositories retain
the legacy callback behavior for tests and do not offer crash durability.

## Exact state machine

- Webhook creation: `pending`, attempt count zero, due immediately.
- Atomic claim: `pending -> delivering`, increment count, create attempt and lease together.
- HTTP 2xx: `delivering -> delivered` with delivery timestamp.
- Retryable failure with budget remaining: `delivering -> pending` with future `next_attempt_at`.
  The attempt outcome is `retry_scheduled`; the public notification enum remains compatible.
- Non-retryable failure or exhausted budget: `delivering -> failed`.
- Expired interrupted delivery: `delivering -> pending` if budget remains, otherwise `failed`.
- Approved `RETRY_NOTIFICATION`: failed webhook -> `pending`, increment delivery generation,
  reset the per-generation count to zero, retain every previous attempt.

Read/unread state is independent. Delivered/failed records are not claimed automatically.
A worker completion requires the current claim token; stale or unowned completions cannot
change state. A claim can begin dispatch only once.

## Retry and failure policy

| Result | Category | Automatic retry |
| --- | --- | --- |
| HTTP 2xx | none | delivered |
| Request/validation timeout, HTTP 408 | timeout | bounded |
| Transport or DNS resolution failure | network | bounded |
| HTTP 429 and 5xx | destination_unavailable | bounded |
| HTTP 401/403 | authentication | terminal |
| Other non-2xx, including redirects | destination_rejected | terminal |
| Malformed configuration or outbound policy rejection | invalid_configuration | terminal |
| Interrupted lease | interrupted | remaining budget only |
| Unexpected delivery exception | unknown | terminal |

For failed attempt `n`, delay is `min(base * 2 ** (n - 1), cap)`.
Defaults are three total attempts, delays of 2 and 4 seconds, and a 60-second cap.
A manual retry starts another bounded generation using the original destination snapshot.
It does not repair invalid credentials or silently change a destination.

| Environment variable | Default | Validation |
| --- | --- | --- |
| NOTIFICATIONS_ENABLED | true | false keeps persisted intent/work without dispatch |
| NOTIFICATION_POLL_INTERVAL_SECONDS | 1 | finite, positive |
| NOTIFICATION_MAX_ATTEMPTS | 3 | 1?20 |
| NOTIFICATION_RETRY_BASE_SECONDS | 2 | finite, positive |
| NOTIFICATION_RETRY_CAP_SECONDS | 60 | finite, positive |
| NOTIFICATION_LEASE_SECONDS | 120 | finite, at least 65 seconds |

The maximum request setting is 60 seconds. DNS validation has a two-second deadline;
HTTP has a total deadline and cannot consume more than its remaining lease minus one second.
Requests never follow redirects. Existing outbound SSRF validation and HMAC/header protections remain.

## Persistence, concurrency and recovery

Additive initialization migrates Stage 22 databases without deletion. Existing records keep
states and receive a three-attempt budget and generation zero. Historical attempts predating
Stage 23 cannot be reconstructed and are not fabricated.

`BEGIN IMMEDIATE` serializes selection and claiming across independent SQLite connections.
Each claim has a random token, an expiry, and a unique `(notification_id, generation, attempt_number)`
attempt record. Dispatch uses an additional atomic gate, so invoking one claimed object twice
cannot send twice. Workers claim only available capacity, avoiding an in-memory backlog of leases.
SQLite work in the worker is offloaded from the event loop; outbound requests remain asynchronous.
Lifecycle shutdown waits for bounded active sends. Startup and subsequent polls recover expired
leases only; a second worker starting does not reset another live worker's claim.

Attempt history records start/finish, outcome, safe failure category/message, HTTP status and latency.
Interruption closes the previous attempt as `interrupted` with an explicitly unknown remote outcome.

Notification identity is the existing project + incident + event purpose + subscription ID key.
Repeated equivalent creation and outbox replay are suppressed. Separately configured subscriptions
are separate intentional delivery destinations, even if they use the same URL. Connector transition
keys retain their existing transition timestamp identity.

**Delivery is at-least-once across an ambiguous remote acknowledgement/crash boundary.** Database
claims prevent overlapping live dispatch, but cannot make a receiver's side effect atomic with a
local commit. Receivers should deduplicate by `X-SentinelOps-Notification-Id` (also in the payload).
No exactly-once or zero-duplicate guarantee is claimed for a crash after remote acceptance.

## API, desktop and Android

`GET /notifications` retains project/status/channel/read filters and adds `incident_id`.
`GET /notifications/{id}/attempts` exposes safe history and returns 404 for a missing notification.
Responses add `max_attempts`, `delivery_generation`, and `failure_category`; configuration and
claim tokens are excluded. The legacy `POST /notifications/{id}/retry` now returns 409 with
instructions to use an approved SafeAction (404 if missing). This intentional compatibility
restriction closes the previous human-approval bypass.

Desktop cards show destination, attempt count/budget, retry cycle, last/next attempt, delivered
at, and failure category/reason. Retry proposes a SafeAction, presents its concrete ID and destination
with a default-No confirmation, then approves/executes only after Yes. No rejects the action.
Authoritative notification state is fetched after execution; eventual delivery refreshes via polling.
The attempt-history API is available to clients; a full attempt-history desktop panel is deferred.

Android's old direct retry button is hidden and failed notifications explain that retry approval is
available in Windows Control Center. WorkManager incident-ID deduplication and persistent preferences
are unchanged. All Android unit tests, including repeated polling/dedup, are rerun. WorkManager remains
best-effort and potentially delayed, not real-time push. No Android device UI validation is claimed.

## SafeAction validation

Proposal and pre-execution checks require an existing failed webhook in the correct project, with
matching incident linkage when supplied. Existing incident lifecycle, allowlist, fingerprint,
approval and action-claim checks remain. The notification executor uses an atomic failed-state
transition, protecting the final race after policy validation. Early policy aborts now also set
`completed_at`. Audit history remains append-only.

Actual user-approved validation (isolated database, no manually fabricated failure state):

- Notification: `1d533d8d-dee8-4f9f-82b2-99fb92e8681e` in `stage23-terminal`.
- SafeAction: `76a96722-1050-4226-be8e-6a9c4c4c5eb5`.
- Receiver genuinely returned 503 three times; notification became failed.
- Proposal: policy allowed, approval pending. The user explicitly answered ?Approve this validation retry?.
- Local receiver restored; user approval recorded; execution succeeded; generation 1 delivered HTTP 200.
- Preserved attempts: `(0,1,503)`, `(0,2,503)`, `(0,3,503)`, `(1,1,200)`.
- Persisted audit: PROPOSED, POLICY_EVALUATED, APPROVED, EXECUTION_STARTED, EXECUTION_COMPLETED.
- Execution verifies requeue; subsequent API/receiver checks independently verify actual delivery.

## Automated validation

Final backend count: **487 passed**. The final run included `-o faulthandler_timeout=30` for hang diagnostics; no timeout was reported.

| Command | Result |
| --- | --- |
| `python -m pytest tests --ignore=tests/desktop -q` | 487 passed |
| `python -m pytest tests/desktop -q` | 81 passed |
| `python -m pytest tools/validation_gateway/test_gateway.py -q` | 9 passed |
| `.\gradlew.bat testDebugUnitTest --rerun-tasks` (from android, JDK 17) | 32 passed, XML failures/errors 0 |
| `python -m pytest tests -q` (D:\SentinelOpsChaosDemo) | 19 passed |
| `git diff --check` | passed |

Focused tests cover transaction rollback, missing callbacks, replay, project/incident filters,
independent concurrent connection claims, duplicate dispatch, stale completions, unowned completions,
leases, all persisted states across reopen, interrupted final attempt, legacy schema migration,
backoff/cap, eventual delivery/exhaustion, categories, invalid destinations, configuration validation,
secret-safe history/logs, disabled worker, capacity limits, genuine failed-delivery SafeAction flow,
approval requirement, audit and post-approval prerequisite changes. Existing TEST_CONNECTOR coverage passes.
Desktop tests cover legacy/new DTO parsing, details rendering, default-No approval/decline, and
concurrent feed rebuilds while requests are in flight.

Regressions found during implementation were fixed, not skipped: outbox initialization when incident
storage opens first, notification title compatibility, completion time on policy abort, and old test
fixtures with notification/incident mismatches. A timing-sensitive multi-status retry test was split into independent fixtures so one case cannot consume another case's scheduled retry. Earlier retry tests now assert earlier policy rejection;
existing executor-race tests continue to cover the atomic final prerequisite check.

## Manual scenarios and evidence

All HTTP validation uses `127.0.0.1:8023` and controlled receiver `127.0.0.1:9023`.
`tools/stage23_validation/server.py` redirects every backend SQLite dependency to
`runtime/stage23-validation.db`; production `runtime/sentinelops.db` is not reset or edited.
Synthetic application exceptions enter through the normal `/watcher/events` API and deterministic
incident detection. Only the local receiver response codes are controlled; delivery state is not edited.

| Scenario | Observed result |
| --- | --- |
| A: successful application-error alert | `10bfb699-57c3-4da3-a50f-43fe43c4feaa`, delivered on attempt 1, receiver 200 |
| B: transient destination failure | `b6c6d5fe-4a81-44c2-9701-30ebbd14e989`, 503, durable scheduled retry, then 200 on attempt 2 |
| C: terminal failure | genuine three 503 attempts, failed state and attempt history persisted |
| D: human-approved retry | action/notification above, succeeded and delivered with full audit |
| E: process restart | backend terminated after first transient failure, receiver restored, same DB reopened, same notification delivered on attempt 2 |
| F: duplicate protection | `8771b2b6-cc19-4917-8653-1c4240c49771`; three repeated error events + two active workers, one notification and one receiver 200 |
| Live desktop | passed: ONLINE, successful first delivery, failed 3/3 with HTTP 503/category, and approved retry delivered in cycle 1; redacted destinations and Retry control visible |

Local evidence: `runtime/stage23-e2e.json`, `runtime/stage23-transient-before.json`,
`runtime/stage23-provider-receipts.jsonl`, and `runtime/stage23-*-tests.log`.
Runtime validation artifacts are locally excluded from Git; the repeatable server helper is source.

To reproduce: run `python -m tools.stage23_validation.server provider` and separately
`python -m tools.stage23_validation.server backend` from the repo root. Provider status codes are
read from `runtime/stage23-provider-state.json`, e.g. `{"/terminal":503,"/transient":503}`.
Register an isolated project/subscription through the normal APIs; ingest an ERROR event. Change
only the receiver status to 200 to restore it. Restart the backend process against the same DB.
Propose failed-notification retries and obtain concrete human approval before calling approve/execute.
Open the desktop using `python -m desktop.main --url http://127.0.0.1:8023`.
The helper does not clear an existing validation DB and must not be repointed at the production DB.

Final restart also preserved all five notification states/counts and the complete approved-action audit;
receiver request counts exactly matched recorded HTTP attempts. The additional terminal notification
`d7016945-803f-4eb6-a569-6415a8c63388` remains failed after restart and was visually inspected.
Read-only checks confirmed no Stage 23 project or notification records exist in the production DB.

Desktop launch through the shell was rejected by automatic approval review ("blocked by policy").
The user launched the desktop manually with port 8023. An Escape interruption was respected; after
explicit resumption, live screenshot and accessibility inspection completed successfully. No extra
retry was approved or executed during the visual inspection.

The isolated backend (8023), receiver (9023), desktop and validation evidence are left available for
operator review. Both servers bind loopback. Receiver destinations are restored to HTTP 200;
terminal failed notifications remain terminal until a separate human-approved retry.

## Security and operational limits

Generated attempt diagnostics never include response bodies, exception text, headers or secret URLs.
HTTPX/HTTPCore transport logging is suppressed only within notification requests using task-local context;
safe ID/status/category logs remain and unrelated HTTP traffic logging is unchanged. Redaction tests use
canary tokens in URL, query, HMAC secret, Authorization header and response body.
As before, delivery/subscription configurations contain required secrets in the local SQLite store;
protect that database and its backups. Attempt/history APIs do not expose that configuration.
Existing subscription configuration read/edit behavior is preserved.

Existing SSRF validation has a documented DNS pre-resolution/connection rebinding window; Stage 23 does
not claim DNS pinning. No TLS bypass, new external credentials, Render mutations, or broad network listeners
were used. SafeAction operator claims retain the existing trusted-local application security model;
this stage does not introduce multi-user authentication. Migration and delivery tests use isolated DBs.

The durable incident outbox covers incident-created and resolved/closed notification purposes.
Connector transition notifications retain existing callback semantics. No new channel infrastructure or
real-time mobile delivery is claimed. Completed intents and attempt records have no automatic retention
policy in this stage; disk growth requires operator management. Expired delivery recovery can wait up to
the configured lease, deliberately avoiding theft of a live worker's claim.

## Changed files

- `.env.example`, `app/common/config.py`: validated worker settings and defaults.
- `app/incidents/repository.py`, `app/notifications/outbox.py`: transactional incident intents and replay identity.
- `app/notifications/models.py`: failure categories, budgets, generations, leases and safe attempt schema.
- `app/notifications/store.py`: additive migration, atomic claims/dispatch/completion, attempt persistence, recovery and filtering.
- `app/notifications/service.py`: snapshot fan-out/replay, response fields and history access.
- `app/notifications/delivery.py`, `transport_logging.py`: bounded asynchronous delivery, classifications, deadlines, safe diagnostics.
- `app/notifications/dependencies.py`, `app/main.py`: configuration wiring and lifecycle assembly order.
- `app/notifications/routes.py`: incident filtering, history endpoint and approval-only retry boundary.
- `app/actions/policy.py`, `app/actions/store.py`: target/linkage revalidation and completed timestamps on abort.
- `desktop/api/client.py`, `desktop/api/models.py`: new data fields and notification/history reads.
- `desktop/ui/views/notifications_view.py`: delivery details and explicit SafeAction approval flow.
- `android/.../NotificationAdapter.java`: remove direct retry bypass and explain Windows approval.
- `tests/test_stage23_notifications.py`: focused durability, concurrency, recovery, security and end-to-end tests.
- `tests/test_notifications_api.py`, `test_notifications_store.py`, `test_notifications_service.py`, `test_notifications_delivery.py`: API/history and claim-aware lifecycle regressions.
- `tests/test_actions_api.py`, `test_actions_service.py`, `test_incidents_persistence.py`: earlier revalidation assertions and correct target linkage.
- `tests/desktop/test_desktop_views.py`, `test_desktop_concurrency_stress.py`: approval/details and asynchronous regression coverage.
- `tools/stage23_validation/server.py`: loopback-only isolated backend and deterministic receiver.
- `project.md`, `docs/PROJECT_JOURNAL.md`, this report: architecture, results and limitations.

No changes were needed in the chaos-demo repository. Recommended commit message after review:
`Implement Stage 23 durable notification delivery and approved retry recovery`.
