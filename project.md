# SentinelOps — PROJECT.md

## 1. Project Identity

**Project Name:** SentinelOps  
**Project Type:** AI-assisted software reliability and incident-response platform  
**Primary Goal:** Connect a deployed application’s runtime telemetry with its source-code repository, Git history, deployment context, and previous incidents so SentinelOps can detect or receive incidents, investigate them with evidence, propose safe remediations, require human approval before code changes, prepare changes only in isolated Git branches, validate them, and present the result to the developer.

SentinelOps is **reactive, evidence-grounded, and human-controlled**.

The initial product does **not** attempt to predict future crashes or failures with machine learning. Its first responsibility is to respond correctly and explainably to incidents that have already happened or are currently happening.

---

# 2. Product Model

SentinelOps should be experienced by another developer as an **always-running reliability platform**, not as a library that must be deeply embedded into the application being monitored.

A developer connects two primary sources:

```text
1. Source / Project Context
   GitHub / GitLab / local or server-side Git repository

2. Runtime / Telemetry Context
   logs / errors / traces / metrics / deployment events
```

SentinelOps combines both.

```text
Source Repository
      │
      ▼
Project Intelligence
      │
      ▼
Project Knowledge Base
      │
      ├──────────────┐
      │              │
      │              ▼
      │       Investigation Engine
      │              ▲
      │              │
Runtime Telemetry ───┘
      │
      ▼
Incident Detection / Incident Creation
```

The developer should not need to keep VS Code open for SentinelOps to function.

VS Code may later become an optional developer interface, but the always-running system must continue working when the developer’s laptop is offline.

---

# 3. Target User Experience

A future production-style onboarding flow should feel approximately like:

```text
Create SentinelOps Project
        ↓
Connect Source Repository
        ↓
Connect Deployment / Runtime Environment
        ↓
Connect Telemetry Source
        ↓
Configure Notifications
        ↓
Initial Project Intelligence Scan
        ↓
Project Ready
        ↓
Continuous Monitoring
```

Example:

```text
Repository:
GitHub → company/payment-service

Deployment:
Railway / AWS / Vercel / Docker / other

Environment:
production

Telemetry:
Railway logs / CloudWatch / OpenTelemetry / HTTP log ingestion / local collector

Notifications:
Email / Slack / webhook

Status:
Monitoring
```

The exact external integrations are future work. The architecture must not assume only one hosting provider.

---

# 4. Product Architecture

SentinelOps should evolve into four major layers.

## 4.1 Integration Layer

Connects SentinelOps to systems owned by the developer.

Possible source connectors:

```text
GitHub
GitLab
local Git repository
server-side checked-out repository
```

Possible telemetry connectors:

```text
structured log file
HTTP ingestion
Docker logs
Railway log integration
AWS CloudWatch
OpenTelemetry
webhook/event source
optional Sentinel Collector Agent
```

The integration boundary should be language-independent.

A monitored application may be:

```text
Python
Java
JavaScript / TypeScript
Go
.NET
or another language
```

SentinelOps should not require the application itself to run the AI engine.

---

## 4.2 Project + Runtime Intelligence Layer

This layer maintains two types of knowledge.

### Project Intelligence

Built from source code, repository metadata, documentation, configuration, and Git history.

It should eventually understand and index:

```text
files
modules
classes
functions
methods
imports
API routes
service boundaries
configuration files
dependencies
call relationships where practical
deployment files
Git commits
recent code changes
documentation
```

### Runtime Intelligence

Built from production or staging telemetry.

It should normalize:

```text
logs
errors
exceptions
stack traces
request IDs
trace IDs
timestamps
service names
endpoints
severity
deployment/version metadata
metrics where supported
```

These two sources are correlated during investigation.

---

## 4.3 SentinelOps Engine

The core engine performs:

```text
incident management
evidence collection
code retrieval
Git intelligence
LangGraph investigation
root-cause synthesis
evidence validation
historical incident retrieval
remediation proposal
human approval
isolated Git branching
remediation execution
automated validation
```

This is the core logic currently being built.

---

## 4.4 Developer Experience Layer

The developer interacts with SentinelOps through:

```text
web dashboard
notifications
REST API
optional CLI
optional VS Code extension later
```

The dashboard is the primary control center.

A future dashboard should show:

```text
projects
service health
active incidents
live/recent logs
incident timeline
runtime evidence
relevant code
Git changes
historical incidents
RCA
confidence and uncertainty
remediation proposal
human approval
branch status
validation results
```

---

# 5. Control Plane and Optional Collector

SentinelOps should support two deployment styles.

## 5.1 Direct Integration

Where a provider exposes suitable APIs/webhooks/log forwarding:

```text
GitHub ────────────────► SentinelOps
Railway / AWS logs ───► SentinelOps
OpenTelemetry ────────► SentinelOps
```

No local SentinelOps agent is required.

## 5.2 Optional Sentinel Collector Agent

Some environments may benefit from a lightweight local process.

```text
Application / Host
      │
      ▼
Sentinel Collector
      │
      ▼
SentinelOps Control Plane
```

The collector may:

```text
tail logs
forward structured telemetry
report service metadata
report deployed commit/version
perform lightweight local collection
```

The collector must **not** contain the full AI investigation engine.

The control plane owns investigation, memory, remediation, approval, dashboard, and notifications.

For serverless environments such as Vercel, a long-running local agent must not be assumed. Provider integrations, log drains, APIs, webhooks, or telemetry export should be supported instead.

---

# 6. Project Intelligence / Initial Understanding

Before SentinelOps can reliably investigate arbitrary projects, it needs a machine-readable understanding of the connected codebase.

This is called the **Project Intelligence Layer**.

When a project is connected for the first time, SentinelOps should perform an initial deterministic scan.

```text
Repository
    ↓
Scanner
    ↓
Language / Framework Detection
    ↓
Parser / Chunker
    ↓
Symbol Extraction
    ↓
Relationship Extraction
    ↓
Git / Config / Documentation Analysis
    ↓
Project Knowledge Base
```

The initial scan should prefer deterministic analysis before LLM summarization.

The system must not send an entire large repository to an LLM every time an incident occurs.

Instead:

```text
initial onboarding
    → build reusable project knowledge

incident investigation
    → retrieve only relevant project context
```

Possible project-knowledge entries include:

```text
file path
symbol name
symbol type
line range
code chunk
module/service
API route
imports
call relationships
configuration references
external dependency references
Git history
last indexed commit
```

LLMs may enrich interpretation, but deterministic source references remain authoritative.

---

# 7. Incremental Project Updates

Project understanding must not become stale.

After the initial full index, SentinelOps should prefer **incremental updates**.

Example:

```text
GitHub Push
    ↓
Changed files detected
    ↓
Re-index changed files
    ↓
Remove stale symbols/chunks
    ↓
Update project relationships
    ↓
Record new indexed commit
```

A full repository rescan should not be required after every commit.

The project knowledge base should expose which commit/version it currently represents.

---

# 8. Continuous Runtime Monitoring

Continuous monitoring must not mean continuously sending every log line to an LLM.

Preferred flow:

```text
Telemetry Stream
      ↓
Deterministic normalization
      ↓
Rules / thresholds / correlation / provider alert
      ↓
Potential incident?
      ↓ yes
Create / update incident
      ↓
Collect bounded evidence
      ↓
Run AI investigation
```

LLM reasoning activates when:

```text
an incident is created
or
a developer explicitly requests investigation
```

This protects cost, latency, and reliability.

The continuous layer may eventually identify signals such as:

```text
error bursts
repeated 5xx responses
same exception across many requests
provider alert events
health-check failures
dependency failures
deployment-related regressions
```

Initial continuous detection should remain simple and deterministic.

---

# 9. Core Incident Workflow

The intended mature workflow is:

```text
Production Application
        ↓
Telemetry Source
        ↓
Incident Detection / External Alert
        ↓
SentinelOps Incident
        ↓
Collect Runtime Evidence
        ↓
Retrieve Relevant Project Knowledge
        ↓
Inspect Relevant Git History / Recent Changes
        ↓
Retrieve Similar Previous Incidents
        ↓
LangGraph Investigation
        ↓
Evidence-Based Root Cause Analysis
        ↓
Deterministic RCA Validation
        ↓
Remediation Proposal
        ↓
Deterministic Remediation Validation
        ↓
Human Review
   ┌────┼───────────┐
   │    │           │
reject revision   approve
   │    │           │
   └────┴─────┐     ▼
              │  Create Isolated Branch
              │     ↓
              │  Apply Approved Remediation
              │     ↓
              │  Build / Test / Reproduce
              │     ↓
              │  Validation Result
              │     ↓
              │  Developer Final Review
              │     ↓
              └── Developer Decides Merge
```

SentinelOps must never automatically merge to the production branch.

---

# 10. Main Project Principles

## 10.1 Human Control

AI components may:

```text
investigate
reason
retrieve
recommend
prepare changes
validate isolated changes
```

They must not silently:

```text
merge into main
deploy to production
delete production data
modify production secrets
execute destructive infrastructure operations
disable security controls
rewrite Git history
discard developer changes
```

Developer approval is required before a generated remediation may be applied.

A separate final developer decision is required before merge/deployment.

---

## 10.2 Evidence Before Conclusions

SentinelOps must never present an unsupported model guess as a confirmed root cause.

Every RCA should distinguish:

```text
observed fact
retrieved evidence
inference
confidence
uncertainty
contradiction
```

References should be preserved where practical:

```text
runtime evidence ID
request ID
trace ID
file path
symbol
code chunk ID
Git commit ID
deployment ID
historical incident ID
```

Historical incidents are advisory context, not replacements for current evidence.

---

## 10.3 Deterministic Components Before AI

Where deterministic logic can solve a task reliably, prefer it.

Examples:

```text
file scanning
AST parsing
Git commands
evidence normalization
branch safety checks
schema validation
review lifecycle
incident correlation thresholds
```

Use LLM reasoning where interpretation is genuinely needed.

---

## 10.4 Isolation

Generated code changes must be isolated.

```text
trusted base branch
      ↓
sentinel/incident-<incident-id>-fix
      ↓
approved change
      ↓
build/tests
      ↓
isolated verification
      ↓
developer review
```

No automated direct modification of `main`.

---

## 10.5 Reactive, Not Predictive

The initial product does not attempt ML-based failure prediction.

Do not add:

```text
future crash forecasting
failure probability prediction
predictive maintenance
traffic forecasting
```

unless explicitly approved as a later separate product capability.

---

# 11. Development Governance

## 11.1 Stage Gate Rule

Every stage must be independently implemented, tested, manually verified, and explicitly approved.

```text
Agent plans current stage
        ↓
User reviews plan
        ↓
Agent implements current stage
        ↓
Automated tests
        ↓
User manually verifies
        ↓
User approves
        ↓
Commit / push
        ↓
Next stage
```

The coding agent must never implement future stages simply because they are documented in this file.

---

## 11.2 Plan Before Implementation

For substantial stages:

1. read `PROJECT.md`,
2. read `docs/PROJECT_JOURNAL.md`,
3. inspect completed implementation and tests,
4. return a plan only,
5. wait for approval,
6. implement only after plan approval.

---

## 11.3 No Automatic Commit or Push

The coding agent must never automatically:

```text
git add
git commit
git push
git merge
```

unless the user explicitly requests that exact Git action.

Normal stage implementation ends with uncommitted changes for user verification.

---

## 11.4 Protect Completed Features

Before modifying existing behavior:

1. identify impacted modules,
2. preserve approved APIs unless change is justified,
3. add regression tests,
4. run relevant old tests,
5. run the complete suite before completion,
6. avoid broad refactors.

---

## 11.5 No Silent Fixes

Unexpected implementation problems must be recorded in the journal.

Document:

```text
Problem
Observed behavior
Suspected cause
Attempted solution
Result
Final solution
Why final solution worked
```

Do not repeatedly mutate unrelated components until tests happen to pass.

---

## 11.6 Code Quality

Prefer:

```text
small modules
clear interfaces
typed domain models
centralized configuration
dependency injection where useful
structured logging
deterministic safety logic
isolated adapters
testable functions
```

Comments should explain **why**, not trivial syntax.

Avoid premature abstraction.

---

# 12. Mandatory Project Journal

Maintain:

```text
docs/PROJECT_JOURNAL.md
```

Every stage should contain:

```markdown
## Stage X — <Name>

### Objective

### Design Decision

### Files Added / Changed

### Problems Encountered

### Attempts

### Final Solution

### Why It Worked

### Verification

### Known Limitations

### User Approval

Pending / Approved
```

Do not rewrite history to hide failed attempts.

---

# 13. Architecture Boundaries

Current and future architecture should remain modular.

Conceptual packages may include:

```text
app/
├── incidents/
├── telemetry/
├── retrieval/
├── repository/
├── project_intelligence/
├── integrations/
├── detection/
├── investigation/
├── workflows/
├── memory/
├── remediation/
├── validation/
├── notifications/
├── reports/
├── api/
├── storage/
└── common/
```

Not every folder must exist immediately.

A future concept listed here is **not permission to implement it early**.

---

# 14. Core Data Models

## 14.1 Project

Represents a monitored software project.

Possible fields:

```text
project_id
name
repository_source
repository_identifier
default_branch
environment
created_at
status
last_indexed_commit
```

## 14.2 Service

Represents a deployable/runtime component.

Possible fields:

```text
service_id
project_id
name
environment
runtime_source
deployment_provider
current_version
current_commit
health
```

## 14.3 Project Knowledge

Represents indexed repository understanding.

Possible fields:

```text
project_id
file_path
symbol_name
symbol_type
line_range
content
relationships
configuration_refs
dependency_refs
indexed_commit
```

## 14.4 Incident

Represents one runtime problem.

Possible fields:

```text
id
project_id
title
status
severity
created_at
detected_at
service
environment
trigger_source
summary
```

## 14.5 Evidence

Represents collected incident information.

Possible evidence types:

```text
runtime_log
metric
trace
stack_trace
git_commit
deployment
source_code
configuration
previous_incident
```

Important metadata may include:

```text
id
incident_id
source
timestamp
service
request_id
trace_id
content
reference
```

## 14.6 Root Cause Analysis

Possible fields:

```text
incident_id
failure_location
triggering_condition
root_cause_hypothesis
affected_component
summary
supporting_evidence
contradicting_evidence
confidence
uncertainties
```

## 14.7 Remediation Proposal

Possible fields:

```text
remediation_id
incident_id
investigation_id
status
summary
target_files
target_symbols
proposed_changes
rationale
risks
validation_steps
evidence_references
validation
assumptions
advisory_historical_context
confidence
created_at
updated_at
```

Remediation status may evolve through:

```text
draft
validated
failed_validation
approved
rejected
revision_requested
```

## 14.8 Remediation Review

Represents a human review decision.

```text
review_id
incident_id
remediation_id
investigation_id
decision
reviewer
comment
created_at
```

Possible decisions:

```text
approved
rejected
revision_requested
```

## 14.9 Remediation Branch

Represents the isolated Git branch authorized by a specific approval.

```text
branch_id
incident_id
remediation_id
approval_id
branch_name
base_branch
base_commit
created_at
```

## 14.10 Validation Result

Represents whether an approved remediation worked.

```text
build_status
tests
incident_reproduction
regressions
runtime_health
summary
```

## 14.11 Incident Memory

Stores trusted completed incident knowledge.

```text
incident_id
symptoms
root_cause
evidence
solution
failed_attempts
successful_fix
affected_components
final_result
```

---

# 15. LangGraph Role

LangGraph orchestrates investigation reasoning and bounded revision.

The graph should operate only after supporting components exist independently.

Current investigation concepts include:

```text
analyze_runtime
      ↓
retrieve_code
      ↓
analyze_code
      ↓
retrieve_git_context
      ↓
analyze_changes
      ↓
retrieve_historical_context
      ↓
synthesize_rca
      ↓
validate_rca
      ↓
bounded revision if required
      ↓
END
```

Do not put every product capability into one giant graph.

Project onboarding, telemetry collection, Git mutation safety, human review, and dashboard behavior may remain outside the investigation graph where that separation is safer.

---

# 16. RAG Role

RAG is used to retrieve bounded project knowledge.

Knowledge categories include:

```text
source code
Git/change history
historical incidents
documentation/runbooks later
configuration
```

RAG must return provenance.

Historical context cannot be used as fabricated evidence for the current incident.

Project-scale retrieval should operate over the maintained project index rather than repeatedly sending the full repository to the model.

---

# 17. Current Controlled Demo Application

The controlled demo application remains the validation target for the core engine.

Current characteristics include:

```text
FastAPI demo application
products/orders
structured logs
request correlation IDs
controlled OrderProcessingError failure mode
safe failure enable/disable endpoints
runtime JSONL evidence
```

The demo application is a development fixture.

It must not become a permanent architectural assumption.

Future integrations should replace hard-coded `demo_app` assumptions with configurable project and telemetry adapters.

---

# 18. Supported Core Incident Types

Initial focus:

## Application Exception

Expected behavior:

```text
collect exception evidence
identify failure path
retrieve relevant source
inspect Git context
produce evidence-grounded RCA
propose remediation
```

## Configuration Failure

Expected behavior:

```text
connect runtime symptoms to configuration
distinguish operational mitigation from source modification
propose safe configuration remediation
```

## Dependency Failure

Expected behavior:

```text
identify external dependency
avoid falsely blaming application code
state uncertainty
recommend bounded remediation/diagnostics
```

## Bad Recent Code Change

Expected behavior:

```text
correlate incident with relevant Git change
identify affected file/symbol
show commit evidence
propose remediation
```

---

# 19. Dashboard / Control Center Vision

The dashboard is not merely a visual wrapper around APIs.

It is the primary developer control center.

Future views should include:

## Overview

```text
project status
connected services
active incidents
recent incidents
service health
monitoring status
```

## Projects

```text
repository connection
deployment/runtime connection
telemetry source
index status
last indexed commit
project structure summary
```

## Live / Recent Telemetry

```text
recent logs
errors
service
severity
request/trace IDs
filters
```

The UI may stream recent events, but it must not imply that an LLM is analyzing every line.

## Incident Detail

```text
timeline
runtime evidence
relevant code
Git context
historical matches
RCA
confidence
uncertainties
remediation
```

## Approval

```text
approve
reject
request revision
review history
```

## Validation

```text
branch
base commit
changed files
build
tests
incident reproduction
regressions
final result
```

## Integrations / Settings

```text
repository
telemetry
deployment metadata
notifications
LLM provider
```

UI work should follow stable backend capabilities.

---

# 20. Notifications

Notifications should inform developers of meaningful events, such as:

```text
new high-severity incident
RCA completed
remediation ready for review
validation failed
validation passed
manual action required
```

A notification should include enough context to act without pretending the notification itself is the complete investigation.

Initial channels may include:

```text
email
Slack
generic webhook
```

Only one channel is necessary for the first working version.

---

# 21. Security Component

Runtime security investigation is a later bounded module.

Potential use cases:

```text
repeated authentication failures
suspicious endpoint usage
unusual application events
```

SentinelOps must not market itself as a replacement for:

```text
WAF
SIEM
EDR
firewall
professional security monitoring
```

Dangerous autonomous security actions remain outside the initial scope.

---

# 22. Daily Reliability Report

A later reporting module may summarize:

```text
availability data when available
incident count
severity
resolved/unresolved incidents
root causes
remediation status
important runtime failures
security events when supported
```

Possible delivery:

```text
dashboard
email
Slack
```

---

# 23. Deployment Philosophy

SentinelOps should ultimately support self-hosted or controlled deployment patterns.

Possible forms:

```text
local developer mode
server/VM service
Docker service
central control plane + optional collector
```

Do not design the product so that it only works when:

```text
VS Code is open
the developer laptop is awake
the monitored app imports SentinelOps directly
the app is written in Python
```

Repository and telemetry connectivity must remain independent from developer-editor uptime.

---

# 24. Explicit Non-Goals for Initial Development

Do not implement until core reliability behavior is stable:

```text
predictive failure forecasting
machine-learning failure prediction
automatic merge to main
automatic production deployment
fully autonomous infrastructure mutation
enterprise RBAC
enterprise SSO
billing
mobile application
custom LLM training
large-scale distributed streaming platform
dozens of specialized agents
full SIEM replacement
complex autonomous Kubernetes remediation
```

Multi-provider integrations should be introduced incrementally rather than all at once.

---

# 25. Implementation Stages

Each stage must produce a visible, verifiable result.

Completed stages must not be silently redefined in a way that invalidates already-approved behavior.

## Stage 0 — Repository Foundation and Development Controls

Goal:

```text
project skeleton
health endpoint
configuration
tests
README
project journal
```

Gate: repository starts and structure is verified.

---

## Stage 1 — Incident Management Core

Goal:

```text
create/read/list incidents
status transitions
typed incident domain
```

Gate: incident APIs manually verified.

---

## Stage 2 — Controlled Demo Application

Goal:

```text
separate demo service
structured logs
products/orders
controlled failure mode
request IDs
```

Gate: normal and controlled-failure behavior verified.

---

## Stage 3 — Telemetry and Evidence Collection

Goal:

```text
collect runtime evidence by request ID
deduplicate evidence
attach evidence to incident
```

Gate: controlled failure produces correct evidence.

---

## Stage 4 — Repository / Source-Code Indexing

Goal:

```text
deterministic source scanning
AST/symbol chunking
source retrieval
```

Current scope may remain demo/Python-specific until the future Project Intelligence stage.

Gate: relevant code retrieval verified.

---

## Stage 5 — Git Change Intelligence

Goal:

```text
read-only Git commits
diffs
file history
safe Git path handling
```

Gate: Git context verified.

---

## Stage 6 — LangGraph Investigation Workflow

Goal:

```text
runtime analysis
code retrieval
Git context
RCA synthesis
evidence validation
bounded revision
```

Gate: RCA matches known controlled failure.

---

## Stage 7 — Incident Memory and Historical RAG

Goal:

```text
store trusted completed incidents
retrieve similar prior incidents
use historical context as advisory only
```

Gate: second related incident retrieves first incident correctly.

---

## Stage 8 — Remediation Proposal

Goal:

```text
generate structured remediation
ground targets in current investigation
validate proposal
do not modify repository
```

Gate: real-provider remediation is semantically correct and repository remains unchanged.

---

## Stage 9 — Human Approval and Isolated Git Branch

Goal:

```text
human approve / reject / request revision
preserve review audit history
allow branch creation only for current approved remediation
create isolated sentinel/incident-<id>-fix branch
do not apply source changes yet
```

Safety:

```text
no source modification
no patch application
no commit
no merge
no push
no reset/stash/clean
```

Gate: branch isolation, approval lifecycle, history, base commit, and idempotency are manually verified.

---

## Stage 10 — Approved Remediation Execution and Automated Validation

Goal:

After Stage 9 approval and branch creation, prepare/apply the approved remediation **only inside the authorized isolated branch** and evaluate it.

Expected capabilities:

```text
generate bounded patch/change
verify target files/symbols
apply only approved remediation scope
build
run tests
reproduce incident where feasible
run regressions
produce structured validation result
```

Must not:

```text
merge
push
deploy production
modify main
silently expand remediation scope
```

Gate: user verifies isolated change and validation results.

---

## Stage 11 — SentinelOps Control Center / Developer Dashboard

Goal:

Create a coherent web interface over stable backend capabilities.

Initial views:

```text
project/monitor overview
incidents
incident detail
runtime evidence
RCA
historical context
remediation
human approval
branch status
validation
recent/live logs where backend support exists
```

Gate: supported end-to-end workflow can be inspected and controlled from the UI.

---

## Stage 12 — Notifications and Alerting

Goal:

Send useful developer notifications for significant incident lifecycle events.

Initial implementation should support one channel such as:

```text
email
Slack
generic webhook
```

Gate: user receives and verifies a real incident notification.

---

## Stage 13 — Project Onboarding and Project Intelligence

Goal:

Transform the current demo-specific source index into a reusable project-understanding subsystem.

Capabilities should be introduced incrementally:

```text
Project domain
repository connection/configuration
initial repository scan
language/framework discovery where practical
symbol/file index
API/config/dependency extraction where practical
project knowledge query API
last indexed commit
incremental re-index of changed files
```

Important:

```text
do not send entire repository to LLM repeatedly
deterministic parsing first
LLM semantic enrichment only where useful
preserve source provenance
```

GitHub may be the first remote repository connector, but the core interfaces must not be GitHub-only.

Gate: connect/index a second sample project and retrieve accurate project context without demo-specific hardcoding.

---

## Stage 14 — Telemetry Connectors and Continuous Incident Detection

Goal:

Allow SentinelOps to receive continuous telemetry from a real external-style source and automatically create/update incidents without manual `/evidence/collect` triggering.

Introduce abstractions such as:

```text
TelemetrySource
TelemetryEvent
TelemetryNormalizer
IncidentDetector
```

Start with a small number of connectors.

Possible first choices:

```text
generic HTTP ingestion
file/log stream adapter
OpenTelemetry-compatible ingestion later
provider-specific connector later
```

Detection should remain deterministic and bounded.

LLM calls must not run for every log event.

Expected flow:

```text
continuous telemetry
      ↓
normalize
      ↓
detect/correlate incident
      ↓
create incident
      ↓
collect bounded evidence
      ↓
trigger investigation
```

Gate: while the developer is not manually triggering collection, a controlled runtime failure creates an incident and launches the supported investigation flow.

---

## Stage 15 — Runtime Security Investigation

Goal:

Analyze selected application-level suspicious events using the same evidence principles.

No autonomous destructive response.

Gate: controlled suspicious event generates evidence-backed explanation and developer alert.

---

## Stage 16 — Daily Reliability Report

Goal:

Generate a daily operational summary from stored project/incident data.

Gate: report matches known stored events.

---

## Stage 17 — Hardening and Final Integration

Goal:

Make the complete product workflow reliable and demonstrable.

May include:

```text
persistence upgrades
adapter failure handling
timeouts/retries
configuration cleanup
security review
integration tests
end-to-end tests
documentation
deployment packaging
demo environment
```

Final demonstration should include:

```text
connected project
project index
continuous telemetry
automatic incident
evidence-grounded RCA
historical context
remediation
human approval
isolated branch
validation
dashboard
notification
```

---

# 26. Current Development Status

As of this PROJECT.md revision:

```text
Stages 0–8: implemented, manually verified, committed
Stage 9: implemented by coding agent, automated tests reported passing, awaiting final manual user verification and approval
Stages 10+: not authorized
```

The coding agent must inspect `docs/PROJECT_JOURNAL.md` and Git history for the exact implementation record.

This status section does not replace the journal.

---

# 27. Stage Completion Report Format

At the end of every implementation stage, the coding agent must report:

```text
STAGE COMPLETED: <stage>

1. What was implemented
2. Files added
3. Files modified
4. Design decisions
5. Problems encountered
6. How problems were solved
7. Tests executed
8. Test results
9. How to run this stage
10. What the user should observe
11. Manual verification steps
12. Known limitations
13. Project journal updated: YES/NO
14. User Approval: Pending
15. Ready for user verification

STOP.
Do not start the next stage.
Do not commit or push unless explicitly requested.
```

---

# 28. Rules for Errors

If a stage fails:

1. do not hide the error,
2. do not start the next stage,
3. record it in the journal,
4. identify the smallest likely cause,
5. fix only what is necessary,
6. re-run current tests,
7. re-run regressions,
8. explain what changed,
9. wait for user verification.

---

# 29. Rules for Dependencies

Before adding a dependency:

```text
confirm real requirement
check whether existing dependency already solves it
prefer maintained libraries
avoid unnecessary paid-service lock-in
document dependency
```

Secrets and API keys must never be committed.

Use environment variables and `.env.example`.

---

# 30. Testing Philosophy

Tests should include, as relevant:

```text
unit tests
integration tests
workflow tests
retrieval tests
Git-operation tests
incident lifecycle tests
remediation safety tests
connector tests
project-index tests
detection tests
regression tests
```

Critical invariants must have explicit tests.

Examples:

```text
no remediation branch without human approval
rejected remediation cannot authorize branch
old approval cannot authorize regenerated proposal
AI cannot modify main
missing evidence cannot produce fake confident RCA
historical incident cannot masquerade as current evidence
continuous log ingestion does not trigger LLM for every event
project re-index does not silently lose unchanged knowledge
```

---

# 31. AI Reliability Rules

SentinelOps must not fabricate:

```text
logs
Git commits
deployments
tests
source locations
repository relationships
validation results
incident history
```

If evidence is insufficient, return uncertainty or:

```text
Insufficient evidence
```

rather than inventing certainty.

---

# 32. Definition of Core Engine MVP

The **core engine MVP** is complete when Stages 0 through 10 work:

```text
incident
    ↓
evidence
    ↓
source context
    ↓
Git context
    ↓
AI RCA
    ↓
incident memory
    ↓
remediation proposal
    ↓
human approval
    ↓
isolated branch
    ↓
approved change
    ↓
automated validation
```

This proves the central incident-response engine.

---

# 33. Definition of Product MVP

The **product MVP** goes beyond the engine.

A usable external-developer experience requires at minimum:

```text
core engine
+
dashboard
+
notifications
+
project onboarding / project intelligence
+
continuous telemetry ingestion / incident detection
```

This proves SentinelOps can be connected to a project rather than only demonstrated against its bundled demo application.

---

# 34. Final Product Statement

SentinelOps is an AI-assisted incident investigation and recovery platform that connects a software project’s source repository with its runtime telemetry.

It continuously maintains project context, receives or collects operational evidence, and activates bounded AI investigation when incidents occur.

It helps developers answer:

```text
What failed?
Where did it fail?
Why did it fail?
What evidence supports that conclusion?
What changed recently?
Has this happened before?
What remediation is proposed?
What risks does it have?
Did the approved remediation actually work?
```

SentinelOps remains useful even when the developer is offline because repository context, telemetry ingestion, investigation, dashboard state, and notifications belong to the always-running platform rather than the developer’s editor.

Human developers retain control over remediation approval, merge, and production deployment.
