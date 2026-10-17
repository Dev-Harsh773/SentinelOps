# Stage 22 final verification

Final review: 2026-10-18. Live validation: 2026-10-17, 14:25 UTC.

## Status: APPROVED

All mandatory Stage 22 gates passed. Stage 23 was not started. SentinelOps remains
uncommitted and unpushed for the user's review and manual Git actions.

## Deployed application and live chain

Render service `srv-db5010tckfvc738fgv9g` was independently observed Live on
`af6f9b61c3eb4c949d9f02ac1201e68667fa0488`, deployment
`dep-db9o9o6uverc738qtl7g`. Deployment succeeded; public health and normal order
requests succeeded. The chaos repository is clean and matches remote `origin/main`.

All three required environment variables were present. The user rotated the admin
token; the current Render token authenticated protected reset/enable requests with
HTTP 200. No token value was printed or written to source. This verifies the current
token is accepted, not a negative test of the retired token.

A fresh Cloudflare Quick Tunnel targeted only `127.0.0.1:8080`. Render's webhook URL
was updated to its `/connectors/conn-c4f83b08/ingest` route. Public `/projects`
returned 404; automated checks verify other methods/routes are rejected. Port 8000
remained loopback-only. The transient hostname is deliberately omitted from source.
The first editor save raced lazy value loading and retained the old URL; this was
caught, corrected, saved, and independently read back before the live failure.

Both chaos flags were reset, health returned 200, and a normal order returned 201.
Exactly one controlled deployed order failure was triggered, returning HTTP 500:

- Request ID: `c88d2532-ae9a-4a98-8e6c-fcd99c5ad958`.
- Canonical event: `evt-525824e70b21`.
- New HIGH incident: `f90bdf42-1c6a-4dd7-825e-71dabc79f67c`.
- Evidence: `e569b3d5-49b0-419f-9ddc-2338382ab7f0`.

The real chain was Render -> Cloudflare -> restricted gateway -> authenticated
webhook -> persisted watcher event -> incident evidence. Both stored event and
evidence preserve ERROR, `order.processing.failed`, `OrderProcessingError`,
`/orders`, status 500, matching response/request ID, and the Render traceback through
`app/api/orders.py:22` / `create_order`. Evidence stores HTTP status and traceback
in metadata. `trace_id` is null: this producer generates a request ID, not a trace ID.
No intended rich HTTP/error context was lost in this path.

## Investigation, remediation, desktop, and persistence

Investigation `1aa8b708-bc9e-4461-b8e1-709164c88851` completed with validation valid.
The RCA identifies `create_order`, `OrderProcessingError`, and the controlled
`app_state.fail_order_processing` condition. Historical matching returned prior
incidents. Provider is mock/deterministic; no live OpenAI reasoning is claimed.

Remediation `f242b71b-0667-461c-93a8-d261566cc225` is validated and targets
`sentinelops-chaos-demo/app/api/orders.py:create_order`, despite the handler ranking
first in retrieval. Its runtime evidence ID matches the live evidence and its code
reference is `chunk-c0dd12a3c833eedc`, the root-cause function. This is an advisory
proposal, not an executed patch or independently proven remediation efficacy.

The actual Windows Control Center was opened, closed, and reopened after backend
restart. Summary, resolved status, Evidence, AI Investigation, Remediation, Timeline,
and Report were inspected. This found and fixed a real legacy DTO mismatch: canonical
`level` was ignored and ERROR displayed as INFO. The DTO now accepts canonical API
fields with legacy fallbacks, and Evidence displays event, endpoint, HTTP status,
exception, request/trace IDs, and traceback. Two regression tests cover this behavior.
The reopened native UI showed ERROR and all rich context correctly.

The Investigate button intentionally updates lifecycle status; it does not launch
an RCA job. Investigation was invoked through the supported backend endpoint.
No workflow or speculative progress-state change was made.

A graceful backend restart preserved the project, webhook/poller definitions, new
resolved incident, evidence, investigation, remediation, report, historical memory,
and existing successful SafeAction with all five audit entries. Before/after API
snapshots match for durable entities; dynamic connector health and report generation
fields are excluded from exact equality. A fresh desktop integration process also
loaded these persisted artifacts through the real API and rendered a report.

## Health connector idempotency and SafeActions

Two repeated identical creation requests returned `conn-7815d6d9`; no new poller was
created. Regression tests cover atomic reuse across concurrent store instances and
distinct project/configuration/status definitions. `conn-b637bedc` and `conn-2c82f10e`
remain disabled, with history preserved. There is one active identical health poller
in the Stage 22 project. The separately onboarded `sentinelops-chaos-demo-2` retains
its separate project-scoped monitor. No unnecessary health outage was repeated.

TEST_CONNECTOR `025bd00f-a178-4cd6-bcda-6b1034406b8a` remains policy allowed,
human approved, and succeeded after restart. Audit: PROPOSED, POLICY_EVALUATED,
APPROVED, EXECUTION_STARTED, EXECUTION_COMPLETED. It was not executed again.
RETRY_NOTIFICATION: NOT EXERCISED; no genuine eligible failed notification exists
for the Stage 22 project (zero notifications). No artificial failure or approval
was created. SafeAction allowlists/approval gates are unchanged.

## Changes and root causes

| File | Change and reason |
| --- | --- |
| `app/connectors/models.py` | Accept optional request ID, trace ID, and traceback; Pydantic previously discarded traceback as an unknown field. |
| `app/connectors/normalizer.py` | Preserve/redact traceback and HTTP status in evidence metadata; use canonical request/trace IDs; retain legacy external-event-ID fallback and metadata.path endpoint fallback. Preserve the pre-existing canonical health-event fix. |
| `app/connectors/store.py` | Atomically reuse an identical poller in the same project using SQLite `BEGIN IMMEDIATE`, including concurrent store instances. |
| `app/connectors/service.py` | Use reuse for poller requests without explicit IDs; do not restart reused workers or return credentials. Explicit-ID creation retains its conflict contract. |
| `app/remediation/llm.py` | Mock provider prefers a uniquely matched RCA symbol over retrieval rank and cites that selected chunk. Ambiguous/unmatched locations retain retrieval order. No orders.py-specific rule. |
| `tests/test_connectors_api.py` | Verify persisted HTTP/stack context, redaction, delivery deduplication, and poller reuse. Isolate watcher storage as well as incident/project stores. Retain pre-existing health-503 regression. |
| `tests/test_connectors_service.py` | Verify concurrent reuse and distinct project/configuration/status boundaries. |
| `tests/test_remediation.py` | Cover simple, qualified, file-qualified, and ambiguous RCA locations. |
| `tools/validation_gateway/gateway.py` | Enforce fixed localhost upstream; stop streamed reads at the body limit; avoid exception text in logs. Existing code accepted arbitrary factory upstreams and buffered the whole body before rejecting it. |
| `tools/validation_gateway/test_gateway.py` | Add fixed-upstream and incremental streaming-limit regressions to the existing seven checks. |
| `desktop/api/models.py`, `desktop/ui/views/incidents_view.py` | Map canonical evidence fields with legacy fallbacks; display ERROR, HTTP context, exception and traceback correctly. |
| `tests/desktop/test_desktop_models.py`, `tests/desktop/test_desktop_actions.py` | Verify canonical/legacy mapping and rendered live-style evidence. |
| `project.md`, `docs/PROJECT_JOURNAL.md`, this report | Record final verified state and limitations. |
| Chaos repo `app/main.py` | Emit endpoint, status 500, and a generated request ID; return that ID in the error response. |
| Chaos repo `app/telemetry.py` | Send the optional canonical HTTP context. Previously it was absent at the producer. |
| Chaos repo `tests/test_telemetry.py` | Expand payload and exception-handler assertions. |

Poller reuse requires exact full configuration and status equality within a
project; display names do not define identity. Requests retain the existing 201
response schema. Explicit IDs allow intentional distinct monitors. Separate
project registrations remain separate, consistent with Stage 21 slug allocation.

Repeated-health evidence suppression is documented Stage 12 behavior, not a new
regression: identical symptoms are suppressed, including background probes,
while correlation has bounded evidence/time windows. It was left unchanged.
Active correlation/suppression indexes remain process-local even though incident
artifacts persist. The desktop Investigate button changes lifecycle status only;
it does not start an RCA job. A new in-progress message would be inaccurate, so no
desktop workflow change was made.

## Final automated regression matrix

Commands run from `D:\SentileOps` unless specified; all results were rerun during
this verification, not copied from the previous handoff.

| Command | Final result |
| --- | --- |
| `python -m pytest tests --ignore=tests/desktop -q` | 445 passed |
| `python -m pytest tests/desktop -q` | 78 passed |
| `python -m pytest tools/validation_gateway/test_gateway.py -q` | 9 passed |
| `python -m pytest tests -q` in `D:\SentinelOpsChaosDemo` | 19 passed |
| `.\gradlew.bat testDebugUnitTest --rerun-tasks` in `android` with configured JDK 17 | BUILD SUCCESSFUL; XML 32 tests, zero failures/errors |
| `git diff --check` in both repositories | PASS |

Desktop count increased from 76 to 78 for the canonical-evidence defect. Final
backend/desktop output is retained locally under ignored `runtime/stage22*`.

## Security, cleanup, and limitations

- Chaos was reset immediately after the single controlled 500. Final public checks:
  health 200, products 200, normal valid order 201. No failure mode remains active
  operationally. No retired-token value was requested or printed.
- The new live incident and old recovered health incident
  `7fb0f18d-69e4-4ab8-8f9b-444561416175` were resolved; history was preserved.
- Final process inspection: no validation backend, gateway, desktop, or cloudflared
  process; no listeners on 8000/8080. The temporary tunnel is stopped. Render retains
  its last temporary URL, which must be replaced before another telemetry session.
- No real connector secret appears in tracked diffs or untracked review files.
  Gateway logs omit credentials; rich context is redacted by normalization. Runtime
  snapshots, screenshots, launchers and backup remain excluded locally, not staged.
- The managed source clone is shallow at `e7df86c`; `app/api/orders.py` is unchanged
  between that commit and deployed `af6f9b6`, verified by Git diff. Root-cause source
  is current, while the indexed exception handler predates the telemetry change.
  No causal Git-change claim is made. Refresh/reindex is needed for future changes.
- Mock RCA still cites the retrieved handler as supporting code; the root-cause
  function is in retrieved context and remediation correctly cites it. Mock
  recommendations remain generic advisory output.
- WorkManager alerts are best-effort and may be delayed, not real-time push.
  No Android device smoke test is claimed; JVM tests and prior Stage 21 scope suffice.
- Quick Tunnel and Render free-instance sleep are validation limitations, not a
  production availability design. Startup can trigger existing unrelated pollers
  and retries; those unrelated configurations were preserved.
- Repeated health symptoms are suppressed by existing bounded correlation rules;
  process-local suppression indexes are not restored on restart.

## Git handoff

SentinelOps remains on `main` at `1dcc50a`, with all Stage 22 changes unstaged and no
agent commit/push. Review includes the untracked report and the three gateway files.
Chaos remains clean at the exact deployed commit and synchronized with origin/main.
Recommended SentinelOps commit message:
`Harden Stage 22 telemetry, desktop evidence, and validation ingress`.

Final tracked diff: 14 files, 505 insertions, 24 deletions. Four additional untracked
review files: this report plus gateway.py, run_gateway.py, and test_gateway.py.
Index is empty; runtime evidence and generated caches are excluded.
