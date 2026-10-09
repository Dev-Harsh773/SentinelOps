# SentinelOps

## 1. Project Status

SentinelOps is complete and manually approved through **Stage 9**.

Current confirmed repository state:

- Active branch: `main`
- Latest confirmed commit: `1f03a81`
- `main` and `origin/main` were aligned at that point
- Full Stage 9 regression: **195 tests passed**
- Stage 9-specific suite: **30 tests passed**
- Stage 10 has **not** been implemented
- The previous Stage 10 direction focused too heavily on automated code patch execution and is now obsolete

This document replaces the older roadmap and is the current architectural source of truth.

---

# 2. Product Definition

SentinelOps is an **always-on AI-assisted incident detection, investigation, operational memory, and response platform**.

Its purpose is to reduce the time between:

> “Something broke”

and:

> “The developer understands what happened, why it happened, what evidence supports that conclusion, whether it happened before, and what should be done next.”

SentinelOps continuously monitors deployed applications, detects abnormal behavior, collects and correlates runtime evidence, investigates likely root causes using telemetry + source code + Git history + deployment context + historical incidents, notifies developers, recommends responses, and optionally performs only small bounded actions after policy validation and explicit human approval.

The core product flow is:

```text
DETECT
  ↓
UNDERSTAND
  ↓
EXPLAIN
  ↓
REMEMBER
  ↓
RECOMMEND
  ↓
NOTIFY
  ↓
OPTIONALLY EXECUTE SMALL SAFE ACTIONS
```

SentinelOps is **not**:

```text
detect problem
→ let AI freely modify production or source code
```

---

# 3. Product Priorities

Priority order:

1. Detection
2. Investigation
3. Root-cause analysis
4. Historical incident memory
5. Recommendation
6. Notification
7. Operational reporting
8. Limited safe actions

Automatic remediation is intentionally a limited feature.

Complex code modification is not the core product identity.

---

# 4. Capability Separation

Every incident must separate three different questions.

## Detection

```text
Is something wrong?
```

Handled primarily by the Sentinel Watcher.

## Diagnosis

```text
Why is it wrong?
```

Handled primarily by the Sentinel Engine.

## Remediation

```text
What should be done?
Can SentinelOps safely do it?
Does a developer need to handle it?
```

Handled by recommendation logic, safety policy, human approval, and eventually the restricted Action Executor.

These capabilities must remain separate.

---

# 5. Core Runtime Architecture

```text
                 COMPANY / USER INFRASTRUCTURE

        ┌────────────────────────────┐
        │      Application(s)        │
        │ API / Web / Workers        │
        └─────────────┬──────────────┘
                      │ telemetry
                      ▼
        ┌────────────────────────────┐
        │      SENTINEL WATCHER      │
        │                            │
        │ collectors                 │
        │ normalization              │
        │ health checks              │
        │ metrics                    │
        │ logs                       │
        │ events                     │
        │ rolling evidence buffer    │
        │ detection                  │
        │ correlation                │
        │ incident trigger           │
        └─────────────┬──────────────┘
                      │
                      ▼
        ┌────────────────────────────┐
        │      SENTINEL ENGINE       │
        │                            │
        │ incident management        │
        │ project knowledge          │
        │ code intelligence          │
        │ Git intelligence           │
        │ deployment context         │
        │ RCA                        │
        │ historical incident RAG    │
        │ recommendation             │
        │ safety classification      │
        │ reports                    │
        └─────────────┬──────────────┘
                      │
                ┌─────┴─────┐
                │           │
                ▼           ▼
        ┌────────────┐  ┌──────────────┐
        │ ANDROID    │  │ WINDOWS      │
        │ MOBILE     │  │ CONTROL      │
        │            │  │ CENTER       │
        │ alerts     │  │              │
        │ summaries  │  │ incidents    │
        │ approvals  │  │ evidence     │
        │ status     │  │ logs/metrics │
        └────────────┘  │ code/Git     │
                        │ RCA/history   │
                        └──────────────┘
```

A future restricted component performs approved write operations:

```text
Watcher
READ ONLY
   ↓
Engine
ANALYZE
   ↓
Safety Policy
   ↓
Human Approval
   ↓
Safety Policy Again
   ↓
Action Executor
LIMITED WRITE
   ↓
Verification
   ↓
Audit
```

---

# 6. Sentinel Watcher

The Sentinel Watcher is the always-on runtime monitoring component.

It must stay lightweight and should primarily perform deterministic work.

The Watcher must not run a large LLM against every log line or request.

Normal operation should look like:

```text
large telemetry volume
        ↓
cheap deterministic processing
        ↓
nothing abnormal
        ↓
AI remains idle
```

Incident operation:

```text
abnormal signal(s)
        ↓
Watcher detects anomaly
        ↓
Watcher creates/updates incident context
        ↓
Sentinel Engine activates
```

## Watcher responsibilities

Eventually the Watcher should be able to:

- receive logs
- receive metrics
- run health checks
- watch process/container state
- observe deployment events
- maintain recent telemetry
- calculate rates and durations
- detect deterministic abnormal conditions
- deduplicate repeated signals
- correlate related signals
- create incident candidates
- freeze incident evidence windows
- trigger the Sentinel Engine
- emit notification events
- report its own health and capabilities

## Watcher permissions

The Watcher is read-only by default.

Allowed examples:

- read logs
- read metrics
- read health state
- read container/process state
- read deployment state
- perform health checks

Not allowed by default:

- cloud administrator privileges
- unrestricted shell/root mutation
- Git writes
- database administration
- arbitrary infrastructure mutation

---

# 7. Sentinel Engine

The Sentinel Engine is the intelligence layer.

It activates when there is an incident worth investigating.

Conceptual flow:

```text
Incident
   ↓
Runtime evidence
   ↓
Project knowledge
   ↓
Code retrieval
   ↓
Git intelligence
   ↓
Deployment context
   ↓
Historical incidents
   ↓
AI investigation
   ↓
Root Cause Analysis
   ↓
Recommendation
   ↓
Safety classification
```

The Engine should answer:

- What happened?
- When did it begin?
- Which service/component was affected?
- What was the impact?
- What likely caused it?
- Which evidence supports the hypothesis?
- What evidence contradicts it?
- How confident is the system?
- Has this happened before?
- What solved similar incidents previously?
- What should be done now?
- Is a safe action available?
- Does a developer need to handle the issue manually?

---

# 8. Project Understanding / Project Knowledge Base

Project understanding is a core component, not optional.

When a repository is connected, SentinelOps should build reusable project intelligence rather than asking an LLM to reread the entire repository during each incident.

The project knowledge system should eventually understand:

- repositories
- files and folders
- symbols
- functions
- classes
- routes/APIs
- imports
- dependencies
- configuration
- services
- important code relationships
- Git history
- recent commits
- deployment metadata
- source index information

Conceptually:

```text
Repository
   ↓
Project Understanding
   ↓
Project Knowledge Base
   ↓
Incident-time retrieval
```

Example:

```text
OrderProcessingError
/orders
       ↓
locate:
- route
- handler/controller
- service
- exception definition
- dependencies
- related recent commits
```

After initial indexing, changed files should be incrementally re-indexed rather than rebuilding everything.

---

# 9. Operational Evidence

SentinelOps is not limited to logs.

The long-term evidence model includes:

- logs
- metrics
- traces
- health checks
- process events
- container events
- deployment events
- infrastructure state
- security-related signals
- Git/deployment changes

Different environments expose different evidence.

Therefore each Watcher/runtime should advertise supported capabilities.

Example conceptual capability set:

```json
{
  "capabilities": [
    "logs",
    "health",
    "metrics",
    "cpu",
    "memory",
    "containers",
    "deployments"
  ]
}
```

Detection rules must only run when the required evidence is available.

---

# 10. Telemetry Normalization

All telemetry sources should eventually normalize their data into a common internal event representation.

The Stage 10 model is named:

```text
TelemetryEvent
```

Stage 10 must define this model concretely in code.

At minimum, the design must support the following concepts when relevant:

- event identity
- timestamp
- project identity
- service identity
- environment
- source
- event type
- severity/level
- message
- request/correlation identifier
- HTTP status
- latency/duration
- exception/error information
- structured metadata

Not every field must be present for every event.

The implementation should use the project's existing modeling conventions and must not introduce a second competing model style without justification.

---

# 11. Collector Architecture

Telemetry collection must use a common abstraction.

Conceptually:

```text
Telemetry Source
      ↓
Collector
      ↓
Normalizer
      ↓
TelemetryEvent
```

The exact Python protocol/interface must be designed during Stage 10 planning after inspecting the existing repository.

The interface must make it possible to add future sources without changing the core Watcher pipeline.

Potential future collectors/connectors include:

- JSONL/file logs
- health checks
- generic HTTP ingestion
- host metrics
- Docker
- CloudWatch/AWS
- Vercel
- Railway
- Kubernetes

Stage 10 implements only the explicitly approved first collectors.

---

# 12. Rolling Evidence Buffer

Evidence must be collected before an incident occurs.

The Watcher maintains recent telemetry so the system can preserve evidence from before the visible failure.

Conceptual behavior:

```text
continuous recent telemetry
        ↓
incident begins
        ↓
freeze relevant incident window
        ↓
continue bounded post-trigger capture
        ↓
evidence bundle
```

The exact time window must be configurable.

Stage 10 creates the buffering/persistence foundation.

Stage 12 adds full incident-window freezing, correlation, and evidence-bundle behavior.

---

# 13. Incident Detection

Initial detection should be deterministic.

Future examples include:

- repeated health-check failures
- 5xx rate spike
- exception burst
- latency spike
- CPU saturation
- memory saturation
- disk pressure
- restart loop
- dependency timeout burst
- authentication failure spike
- deployment followed by increased failures

Static rules may later be enhanced with baselines such as:

- rolling averages
- percent change
- standard deviation
- duration windows

Complex predictive ML is not required for the initial product.

Full detection belongs to Stage 11.

Stage 10 must not prematurely implement the complete detection engine.

---

# 14. Incident Correlation

A single real incident can produce multiple symptoms.

Example:

```text
database timeout
+
500 errors
+
checkout failures
+
health failure
+
container restart
```

These should be eligible to become one incident rather than five unrelated incidents.

Future correlation dimensions include:

- service
- time window
- exception/error
- dependency
- request path
- deployment

Full incident correlation belongs to Stage 12.

---

# 15. Historical Incident Memory

Historical incident memory is a core differentiator.

After an incident is validated/resolved, SentinelOps stores trusted outcome information such as:

- final root cause
- supporting evidence
- actions taken
- result
- recovery time
- useful remediation
- relevant project/service context

Future incidents can retrieve similar trusted historical incidents.

The goal is to turn SentinelOps into organization-specific operational intelligence.

Stage 7 already provides the historical RAG foundation.

Future work should build on it rather than replacing it.

---

# 16. Recommendation Levels

SentinelOps should classify response level.

## A. Explain Only

For complicated, uncertain, or unsafe situations.

Examples:

- database corruption
- complex multi-service failure
- security incident
- unknown infrastructure failure
- architectural problem

SentinelOps provides:

- what happened
- where
- when
- impact
- likely cause
- evidence
- historical context
- investigation guidance
- possible solutions

Developer handles the response.

## B. Recommend Solution

For incidents where a likely response is known but mutation is not automatically appropriate.

SentinelOps generates:

- recommended response
- rationale
- relevant target/context
- risk
- validation steps
- confidence

## C. Small Safe Action

Only bounded and reversible operations.

Possible later examples:

- restart one known unhealthy worker
- restart one known container
- disable a known feature flag
- scale replicas within configured limits
- retry a safe operation
- roll back the immediately previous known-good deployment

Every action must include:

- action type
- target
- reason
- risk
- bounds
- required permissions
- approval
- execution result
- validation
- audit record

---

# 17. Safety Policy

Human approval alone is not sufficient.

Execution flow:

```text
Recommendation
    ↓
Safety Policy
    ↓
Human Approval
    ↓
Safety Policy Again
    ↓
Execution
    ↓
Verification
    ↓
Audit
```

A user must not be able to approve an action outside configured safety bounds.

Security-related automation must be more conservative than normal reliability automation.

---

# 18. Security Incidents

SentinelOps may detect defensive security anomalies, for example:

- login failure spikes
- endpoint scanning behavior
- request floods
- abnormal traffic patterns
- suspicious application activity

The product must avoid making unsupported claims such as:

> “You are being hacked.”

Prefer:

> “Security anomaly detected.”

Then:

```text
collect evidence
→ classify severity
→ notify
→ recommend response
```

Security automation should remain highly restricted.

---

# 19. Notification Architecture

Future notification channels may include:

- Android
- email
- webhook
- Slack
- Discord
- Telegram

Native Android push does not need to be the first notification mechanism.

Webhook/email/chat integrations can provide useful early mobile notification behavior.

---

# 20. Windows Control Center

The Windows Control Center is the deep-investigation client.

Expected long-term areas include:

- overview
- projects
- services
- incidents
- incident detail
- evidence
- logs
- metrics
- traces
- deployment history
- source context
- Git history/diffs
- RCA
- historical matches
- recommendations
- approvals
- integrations
- settings
- reports

Principle:

```text
Phone  = fast decision
Laptop = deep investigation
```

---

# 21. Android Client

The Android app is a client, not the monitoring engine.

Expected responsibilities:

- receive notifications
- show active incidents
- show severity
- show impact
- show start time
- show affected service
- show likely cause
- show concise evidence
- show similar historical incidents
- show recommendation
- acknowledge incident
- approve/reject eligible bounded actions
- show execution/result status

The phone does not need to stay continuously active.

---

# 22. Deployment Topologies

SentinelOps is one product with multiple deployment topologies.

Possible conceptual modes:

- local
- standalone
- distributed
- connector

## Small deployment

```text
Watcher + Engine
in one persistent runtime
```

## Larger company

```text
distributed Watchers
        ↓
central Sentinel Engine
```

## Serverless application

```text
serverless app
      ↓ telemetry/events
persistent Sentinel Runtime
```

The Watcher should run as independent always-on compute close to the monitored application whenever possible.

It does not need to run on the developer laptop or phone.

---

# 23. Same-Machine Monitoring Limitation

If the application and Watcher run on the same host and the entire host disappears, the local Watcher cannot report its own disappearance.

Host-level availability may require external evidence such as:

- cloud instance health
- provider monitoring
- load balancer health
- Kubernetes control plane
- another Watcher
- external uptime checks

This is a fundamental distributed-system limitation and should not be hidden.

---

# 24. Docker Direction

Docker is the preferred eventual universal packaging/runtime approach because it can work across:

- developer machines
- VPS
- EC2
- Railway-like platforms
- company infrastructure
- Kubernetes

Platform-specific helpers/connectors can be added later.

Docker packaging is not the main implementation goal of Stage 10 unless needed to validate the Watcher process boundary.

---

# 25. Generic HTTP Ingestion

Generic HTTP ingestion is important because it allows unsupported platforms to send telemetry without requiring a native connector.

Stage 10 must include a minimal generic HTTP ingestion capability.

The exact endpoint structure must be decided during the Stage 10 plan after inspecting existing API conventions.

Do not assume legacy conceptual examples such as `/telemetry/logs`, `/telemetry/metrics`, and `/telemetry/events` are final route names.

Requirements:

- accept normalized or normalizable telemetry
- validate input
- associate telemetry with project/service identity
- store accepted events
- reject malformed events cleanly
- avoid triggering AI work directly
- expose deterministic, testable behavior

---

# 26. Daily and Weekly Reporting

The reporting layer should eventually generate fact-based reports from stored data.

Possible report information:

- services monitored
- incident count
- severity distribution
- resolved incidents
- top/repeated incidents
- deployment-correlated incidents
- mean recovery time
- safe actions executed
- recommendations awaiting review
- current status
- historical patterns

Reports must come from stored facts rather than unsupported LLM invention.

Reporting belongs primarily to Stage 19.

---

# 27. Existing Completed Stages

## Stage 0 — Foundation ✅

Built:

- FastAPI
- Uvicorn
- pytest
- httpx
- modular application structure
- health endpoint
- configuration/logging
- README/environment setup
- project journal

## Stage 1 — Incident Management ✅

Built:

- incident model
- incident lifecycle
- repository interfaces
- in-memory implementation

Lifecycle:

```text
OPEN
→ INVESTIGATING
→ RESOLVED
→ CLOSED
```

## Stage 2 — Controlled Demo Application ✅

Built independent demo application with deterministic incident behavior.

Includes:

- products/orders behavior
- controlled `OrderProcessingError`
- failure toggle
- request IDs
- structured logs
- health endpoint

## Stage 3 — Telemetry / Evidence ✅

Built runtime log evidence foundation:

- JSONL runtime logs
- request correlation
- evidence collection
- deduplication
- incident-linked evidence

Current flow is still manually triggered.

## Stage 4 — Source Indexing ✅

Built source-intelligence foundation:

- Python AST parsing
- code chunks
- symbol extraction
- deterministic IDs
- search/token ranking

## Stage 5 — Git Intelligence ✅

Built read-only Git investigation:

- commits
- commit details
- diffs
- file history
- safe repository paths

No GitHub API is required for the completed stage.

## Stage 6 — AI Investigation ✅

Built LangGraph investigation flow:

```text
analyze_runtime
→ retrieve_code
→ analyze_code
→ retrieve_git_context
→ analyze_changes
→ historical context
→ synthesize RCA
→ validate RCA
→ bounded revision
```

Supports real/fake LLM provider abstraction.

## Stage 7 — Incident Memory ✅

Built historical RAG for trusted completed/validated incident outcomes.

## Stage 8 — Remediation Proposal ✅

Built recommendation generation including:

- summary
- target files/context
- symbols
- suggested changes/actions
- rationale
- risk
- validation
- confidence

Operational actions are not incorrectly treated as code modifications.

## Stage 9 — Human Approval + Isolated Branch ✅

Built:

- approved
- rejected
- revision requested
- audit records
- safe isolated Git branch creation

Safety properties include:

- no branch without approval
- stale approval cannot approve regenerated remediation
- rejected proposals remain rejected
- review history preserved
- no commit
- no merge
- no push
- no source mutation
- branch operation idempotency

---

# 28. Revised Remaining Roadmap

## Stage 10 — Sentinel Watcher Foundation

Build the runtime and normalized telemetry foundation.

## Stage 11 — Detection Rules + Automatic Incident Creation

Turn telemetry into automatically detected incidents.

## Stage 12 — Incident Correlation + Rolling Evidence Windows

Correlate signals and construct incident evidence bundles.

## Stage 13 — Project Onboarding + Project Knowledge Base

Introduce first-class project/service/environment configuration and reusable project understanding.

## Stage 14 — Deployment / Telemetry Connectors

Expand from generic/local collection to real platform integrations.

## Stage 15 — Notification System

Webhook/email/chat channels first, native push later.

## Stage 16 — Windows Control Center

Build the deep investigation user interface.

## Stage 17 — Android Mobile Client

Build fast incident notification/review/approval client.

## Stage 18 — Safe Action Framework

Implement small bounded actions with policy + approval + verification + audit.

## Stage 19 — Reports + Operational Memory UX

Daily/weekly reports, trends, recovery metrics, repeated incidents, historical operational insights.

## Stage 20 — Security + Hardening + Packaging

Authentication, authorization, secrets, encryption, retention, permissions, rate limits, packaging, Docker/releases/installers and production hardening.

## Stage 21 — End-to-End Application Onboarding & Connection Flow

Complete first-time user onboarding journey: local and public GitHub repository connection, deterministic project ID derivation, concurrency-safe workspace allocation, one-time raw webhook secret delivery with subsequent masking, operational connection readiness monitoring (`/readiness`), Windows Control Center 4-step onboarding wizard, and Android WorkManager best-effort background alert polling.

---

# 29. Stage 10 — Frozen Scope

Stage 10 is now:

> **Sentinel Watcher Foundation**

Its purpose is to create the always-on telemetry runtime that later stages will use.

Stage 10 is infrastructure/foundation work.

It is intentionally **not** the full anomaly detector and **not** automatic remediation.

## Stage 10 must implement

### A. Watcher Runtime

Create a long-running Watcher runtime/process abstraction integrated cleanly with the existing application architecture.

Requirements:

- explicit start/stop lifecycle
- clean shutdown
- health/status visibility
- collector orchestration
- deterministic behavior
- errors in one collector should not silently corrupt unrelated telemetry
- no LLM required

The exact process/module layout must follow the existing repository conventions discovered during planning.

### B. Normalized `TelemetryEvent`

Create one canonical normalized telemetry-event model.

It must:

- represent multiple telemetry types
- include project/service identity
- include timestamp/source/type
- support structured metadata
- allow optional event-specific fields
- be serializable/persistable
- be deterministic and testable

The coding agent must inspect existing models before choosing the final implementation.

### C. Collector Abstraction

Create a small extensible collector contract.

It must support:

- starting/stopping or polling/collection as appropriate
- returning or emitting normalized telemetry
- collector identity/type
- capability advertisement where appropriate
- predictable failure handling

Do not over-engineer a plugin framework in Stage 10.

### D. First Collectors

Stage 10 should implement:

1. JSONL/file log collector
2. Health-check collector
3. Generic HTTP ingestion path

A basic host-metrics collector may be included only if the plan shows it can be added without expanding the stage materially.

A Docker collector foundation may be designed, but full Docker monitoring belongs in a later connector stage unless implementation is very small and clearly isolated.

### E. Generic HTTP Ingestion

Provide an API-based way to submit telemetry.

Must:

- validate input
- normalize into `TelemetryEvent`
- associate with known project/service identity
- persist accepted telemetry
- return clear validation failures
- remain deterministic
- not perform AI investigation

Exact routes must match current application conventions.

### F. Local Persistence

Use a simple local persistence layer suitable for the Watcher foundation.

Preferred initial direction:

```text
SQLite
```

However:

- reuse an existing project persistence abstraction if one already exists
- do not introduce a competing persistence pattern unnecessarily
- keep the storage layer replaceable
- schema must be migration-friendly
- tests must not rely on a developer's real local database

Stage 10 persistence should support at least:

- telemetry events
- service/project registration needed by telemetry
- Watcher/runtime status if persistence is appropriate

### G. Rolling Buffer Foundation

Create a bounded recent-telemetry access mechanism.

Requirements:

- bounded by time, count, or both
- configurable
- deterministic
- no unbounded in-memory growth
- recent events retrievable by service/project and time range

Full incident evidence freezing belongs to Stage 12.

### H. Project / Service Identity Foundation

Stage 10 needs the minimum identity required to reliably attach telemetry to the correct monitored service.

Do not build the complete onboarding system yet.

Minimum requirement:

```text
project
  ↓
service
```

Environment identity should be included if it already fits the existing incident model cleanly.

Full onboarding/domain modeling belongs to Stage 13.

### I. Watcher Health / Status

Expose enough status to answer:

- Is the Watcher running?
- Which collectors are active?
- Which collectors are unhealthy?
- What capabilities are available?
- When was telemetry last received?

Exact API shape must follow existing conventions.

---

# 30. Stage 10 Explicit Non-Goals

Stage 10 must NOT implement:

- full detection rules
- automatic incident creation
- incident correlation
- full evidence-window freezing
- AI anomaly detection
- new RCA logic
- new remediation generation
- automatic patch generation
- source-code mutation
- safe-action execution
- native Vercel connector
- native Railway connector
- full AWS/CloudWatch connector
- full Kubernetes connector
- full Docker monitoring unless separately approved
- Windows UI
- Android app
- push notifications
- full project onboarding
- production authentication/authorization overhaul

Do not jump ahead.

---

# 31. Stage 10 Acceptance Criteria

Stage 10 is complete only when all of the following are true.

## Architecture

- [ ] Watcher is represented as a clear runtime component
- [ ] collector abstraction exists
- [ ] one canonical `TelemetryEvent` exists
- [ ] current Stage 0–9 behavior remains intact
- [ ] no obsolete automatic-patch Stage 10 behavior is introduced

## Telemetry

- [ ] JSONL/file telemetry can be ingested
- [ ] health-check telemetry can be produced
- [ ] generic HTTP telemetry can be accepted
- [ ] telemetry from all Stage 10 sources reaches the same normalized model
- [ ] invalid telemetry is rejected predictably

## Identity

- [ ] telemetry is associated with the correct project/service
- [ ] unknown or invalid identity behavior is explicitly defined and tested

## Persistence

- [ ] accepted telemetry survives process-level storage boundaries expected by the Stage 10 design
- [ ] tests use isolated storage
- [ ] storage cannot grow without an explicit retention/bounding strategy

## Rolling access

- [ ] recent telemetry can be queried deterministically
- [ ] result filtering by project/service/time is covered
- [ ] bounded buffer behavior is tested

## Runtime

- [ ] Watcher health/status is observable
- [ ] collector status is observable
- [ ] collector failure behavior is defined
- [ ] clean startup/shutdown is tested

## Safety

- [ ] Watcher requires no write permission to Git
- [ ] Watcher performs no infrastructure mutation
- [ ] Stage 10 performs no source-code mutation
- [ ] no automatic remediation is introduced

## Regression

- [ ] Stage 10-specific tests pass
- [ ] full test suite passes with:

```bash
python -m pytest -v
```

- [ ] no existing Stage 0–9 tests are intentionally weakened or deleted to make Stage 10 pass

## Manual Verification

Manual verification must demonstrate at least:

```text
start SentinelOps/Watcher
        ↓
register/use test project + service
        ↓
ingest telemetry by HTTP
        ↓
read JSONL/file telemetry
        ↓
run health-check collector
        ↓
confirm normalized events
        ↓
confirm persistence
        ↓
confirm recent-event retrieval
        ↓
confirm Watcher/collector health
        ↓
restart where relevant
        ↓
confirm expected persisted state
```

The journal remains Pending until this verification is completed.

---

# 32. Stage 11 Preview

Stage 11 will consume Stage 10 telemetry and introduce deterministic detection.

Planned examples:

- repeated health-check failure
- 5xx spike
- exception burst
- latency spike
- CPU/memory threshold breaches where data exists
- dependency timeout bursts
- restart signals where data exists

Flow:

```text
TelemetryEvent
      ↓
Detection Rule
      ↓
Trigger
      ↓
Incident automatically created
```

No manual incident creation should be required for covered cases.

Stage 11 is where the Watcher begins automatically turning telemetry into incidents.

---

# 33. Stage 12 Preview

Stage 12 introduces:

- rolling incident windows
- pre-incident/post-incident evidence capture
- event deduplication
- signal correlation
- incident evidence bundles

Example:

```text
database timeout
+
HTTP 500 burst
+
health failure
        ↓
one correlated incident
```

---

# 34. Development Workflow

The strict stage-gate workflow remains unchanged.

For every future stage:

1. Define/freeze stage scope.
2. Give coding agent a **PLAN-ONLY** prompt.
3. Coding agent inspects repository and returns plan.
4. Review plan critically.
5. Correct scope/architecture if necessary.
6. Explicitly approve plan.
7. Send implementation prompt.
8. Agent implements only the approved stage.
9. Run automated tests.
10. Perform manual verification.
11. Keep journal status Pending until manual verification.
12. User approves stage.
13. Journal becomes Approved.
14. Commit.
15. Push.
16. Only then begin the next stage.

Coding agent rules:

```text
NEVER commit
NEVER push
NEVER jump ahead
NEVER silently redefine architecture
NEVER weaken tests to make implementation pass
```

---

# 35. Coding-Agent Repository Inspection Rule

This document defines architecture and product behavior.

It does **not** invent repository details that must be discovered from the actual code.

Before planning a stage, the coding agent must inspect:

- current repository tree
- `PROJECT.md`
- `README`
- existing application entrypoints
- existing domain models
- repository abstractions
- configuration system
- current test organization
- journal
- relevant completed-stage modules

The agent must reuse existing conventions wherever practical.

If the current repository conflicts with this document, the agent must report the conflict in the plan rather than silently choosing a direction.

---

# 36. Source of Truth

`PROJECT.md` is the project source of truth for:

- product identity
- major architecture
- stage definitions
- stage boundaries
- non-goals
- workflow
- safety principles

The project journal records what was actually implemented and verified.

Code and tests remain the source of truth for exact implemented interfaces.

---

# 37. Current Next Action

The architecture in this document is now considered frozen enough to continue development.

The next action is **not implementation**.

The next action is:

```text
Coding Agent
   ↓
Read this PROJECT.md
   ↓
Inspect real repository
   ↓
Produce Stage 10 PLAN ONLY
   ↓
No code changes
```

The Stage 10 plan must resolve the implementation details intentionally left repository-dependent here, including:

- exact module/file placement
- exact `TelemetryEvent` fields/types
- exact collector protocol
- exact SQLite/storage abstraction and schema
- exact rolling-buffer implementation
- exact HTTP ingestion routes
- exact Watcher lifecycle model
- exact project/service identity integration
- configuration keys
- retry/error semantics
- migration strategy if needed
- Stage 10 test matrix
- manual verification steps

Only after the plan is reviewed and explicitly approved should Stage 10 implementation begin.
