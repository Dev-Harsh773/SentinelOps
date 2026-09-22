# SentinelOps — PROJECT.md

## 1. Project Identity

**Project Name:** SentinelOps  
**Project Type:** AI-assisted software reliability and incident-response platform  
**Primary Goal:** Detect an application incident, collect relevant evidence, investigate the root cause using runtime telemetry + source-code knowledge + Git history + previous incidents, propose a safe fix, require developer approval, apply the fix only in an isolated Git branch/environment, validate it, and present the result for final developer review.

SentinelOps is **reactive**, not predictive.

This project does **not** attempt to predict future crashes, future load, future failures, or future incidents using machine learning. The first objective is to respond correctly and explainably to incidents that have already occurred or are currently occurring.

---

# 2. Core Product Idea

A deployed application may fail because of application bugs, configuration changes, dependency failures, database issues, infrastructure issues, or other runtime problems.

Traditional monitoring tools can tell developers that something is wrong, but developers often still need to manually inspect:

- logs,
- metrics,
- traces,
- stack traces,
- recent commits,
- recent deployments,
- source code,
- dependency relationships,
- previous incidents,
- previous fixes.

SentinelOps adds an AI investigation and recovery layer on top of this information.

The intended high-level flow is:

```text
Application Incident
        ↓
Monitoring / Telemetry Detects Problem
        ↓
SentinelOps Creates Incident
        ↓
Collect Runtime Evidence
        ↓
Retrieve Relevant Source Code
        ↓
Inspect Recent Git Changes
        ↓
Retrieve Similar Previous Incidents
        ↓
LangGraph Investigation Workflow
        ↓
Evidence-Based Root Cause
        ↓
Proposed Solution
        ↓
Developer Reviews and Approves
        ↓
Create Isolated Git Branch
        ↓
Apply Proposed Fix
        ↓
Build / Test / Reproduce Incident
        ↓
Validation Result
        ↓
Developer Reviews Final Result
        ↓
Developer Decides Whether to Merge
```

SentinelOps must never directly modify the production branch as part of the normal automated workflow.

---

# 3. Main Project Principles

These rules apply to the entire project.

## 3.1 Human Control

AI agents may investigate, reason, recommend, and prepare changes.

They must not silently:

- merge into the main branch,
- deploy to production,
- delete production data,
- modify production secrets,
- execute destructive infrastructure operations,
- disable security controls,
- change repository history,
- overwrite developer work.

Developer approval is required before any generated remediation patch is applied.

A second developer review is expected before merging the remediation branch.

---

## 3.2 Evidence Before Conclusions

SentinelOps must not present an unsupported AI guess as a confirmed root cause.

Every root-cause result should distinguish between:

- observed fact,
- retrieved evidence,
- inferred hypothesis,
- confidence level,
- unresolved uncertainty.

Where possible, a result must reference evidence such as:

- log lines,
- trace IDs,
- metric observations,
- stack traces,
- file paths,
- function names,
- Git commit IDs,
- deployment IDs,
- incident IDs.

---

## 3.3 Existing Monitoring Before AI

LLMs must not continuously analyze every request or every metric.

Standard monitoring and observability systems are responsible for continuous collection and detection.

AI reasoning activates only when an incident is created or when a developer explicitly requests an investigation.

This avoids unnecessary cost and complexity.

---

## 3.4 Isolation

Generated changes must be isolated.

Normal remediation sequence:

```text
main
  ↓
sentinel/incident-<id>-fix
  ↓
AI-generated changes
  ↓
build
  ↓
tests
  ↓
isolated runtime
  ↓
verification
  ↓
developer review
```

No automated direct modification of `main`.

---

## 3.5 Incremental Development

The project must be developed in independently verifiable stages.

The AI coding agent must complete only the currently assigned stage.

It must stop after that stage and report:

1. what was implemented,
2. which files changed,
3. how to run it,
4. what the user should observe,
5. how to verify it,
6. known limitations,
7. any errors encountered,
8. what was added to the project journal.

It must **not begin the next stage** until the user explicitly confirms that the current stage is working.

---

# 4. Development Governance

The coding agent must follow these rules throughout the project.

## 4.1 Stage Gate Rule

Every implementation phase has a gate.

A stage is complete only when:

- implementation is finished,
- required tests pass,
- the user can visibly verify the expected behavior,
- documentation is updated,
- the agent reports the result,
- the user explicitly approves the stage.

Example:

```text
Agent completes Stage 3
        ↓
Agent explains expected behavior
        ↓
User runs / checks Stage 3
        ↓
User says it is correct
        ↓
Only then Stage 4 may begin
```

---

## 4.2 No Unrequested Scope Expansion

The coding agent must not add:

- unrelated frameworks,
- unrelated services,
- unnecessary abstraction,
- extra UI pages,
- additional agents,
- cloud dependencies,
- authentication systems,
- machine-learning prediction,
- Kubernetes,
- complex event streaming,
- paid services,

unless they are explicitly part of the current approved stage.

Simple and correct is preferred over impressive but fragile.

---

## 4.3 Protect Completed Features

Before changing existing code, the coding agent must consider whether the change can affect previously approved functionality.

For every stage after the first stable feature, it must:

1. identify existing modules that could be affected,
2. preserve existing APIs unless change is required,
3. run existing tests,
4. add regression tests where appropriate,
5. avoid broad refactoring unless explicitly approved.

If a new feature can be implemented independently, it should be isolated rather than rewriting a working component.

---

## 4.4 No Silent Fixes

If the agent encounters an unexpected problem, it must not repeatedly alter unrelated code until something happens to work.

It must document:

```text
Problem
Observed behavior
Suspected cause
Attempted solution
Result
Final solution
Why final solution worked
```

This information must be written into the project journal.

---

## 4.5 Code Comments

Code must contain useful comments where reasoning is not obvious.

Comments should explain **why**, not repeat simple syntax.

Good:

```python
# Keep remediation changes isolated from main so an AI-generated patch
# cannot modify the developer's production branch before approval.
```

Bad:

```python
# Create branch
```

Do not over-comment trivial code.

Public modules/classes/functions should have concise documentation where helpful.

---

## 4.6 Code Quality

The coding agent should prefer:

- small modules,
- clear names,
- explicit interfaces,
- typed models where practical,
- centralized configuration,
- testable functions,
- dependency injection where it genuinely improves testing,
- structured logging,
- deterministic behavior around critical operations.

Avoid premature abstractions.

---

# 5. Mandatory Project Journal

A living project journal must be maintained from the beginning.

Suggested file:

```text
docs/PROJECT_JOURNAL.md
```

It is separate from this `PROJECT.md`.

The journal must record actual development history.

Each stage should add an entry similar to:

```markdown
## Stage X — <Name>

### Objective

What we intended to build.

### Design Decision

Why the implementation was designed this way.

### Files Added / Changed

List of relevant files.

### Problems Encountered

What went wrong during implementation.

### Attempts

What approaches were tried.

### Final Solution

What ultimately worked.

### Why It Worked

Technical explanation.

### Verification

How the feature was tested.

### Known Limitations

Current limitations.

### User Approval

Pending / Approved.
```

Never rewrite history to make development look perfect.

Failed approaches are useful project knowledge and must remain documented.

---

# 6. Architecture Boundaries

SentinelOps should be modular.

Initial conceptual modules:

```text
sentinelops/
│
├── api/
│
├── incidents/
│
├── telemetry/
│
├── repository/
│
├── retrieval/
│
├── agents/
│
├── workflows/
│
├── remediation/
│
├── validation/
│
├── notifications/
│
├── reports/
│
├── storage/
│
└── common/
```

The exact structure can evolve during implementation, but modules should remain logically separated.

---

# 7. Core Data Model

The project should eventually have first-class concepts for:

## Incident

Represents one runtime problem.

Possible fields:

```text
id
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

---

## Evidence

Represents information collected for an incident.

Examples:

```text
log
metric
trace
stack_trace
git_commit
deployment
source_code
previous_incident
```

Important metadata:

```text
source
timestamp
content
location/reference
incident_id
```

---

## Root Cause Analysis

Represents the investigation result.

Possible structure:

```text
incident_id
hypothesis
confidence
supporting_evidence
contradicting_evidence
affected_component
affected_files
uncertainties
```

---

## Remediation Proposal

Represents a proposed solution.

```text
incident_id
description
affected_files
expected_effect
risk
patch
status
```

Possible status:

```text
proposed
approved
rejected
applied
validation_failed
validation_passed
```

---

## Validation Result

Represents whether the proposed fix worked.

```text
build_status
tests
incident_reproduction
regressions
runtime_health
summary
```

---

## Incident Memory

Stores completed incidents for future retrieval.

```text
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

# 8. LangGraph Role

LangGraph is used to orchestrate investigation state and controlled transitions.

It should not be introduced until the underlying components needed by the workflow are individually functional.

The eventual investigation graph may resemble:

```text
START
  ↓
Incident Classification
  ↓
Evidence Collection
  ↓
Runtime Analysis
  ↓
Code Retrieval
  ↓
Git Change Analysis
  ↓
Past Incident Retrieval
  ↓
Root Cause Synthesis
  ↓
Evidence Validation
  ↓
Solution Proposal
  ↓
Human Approval Gate
  ↓
Patch Preparation
  ↓
Validation
  ↓
END
```

Nodes must have clear inputs and outputs.

Workflow state must be inspectable.

Human approval must be represented as a real workflow boundary rather than simulated approval.

---

# 9. RAG Role

RAG is used where external project knowledge must be retrieved.

Eventually SentinelOps should retrieve from several knowledge categories.

## Source Code Knowledge

Used to identify relevant:

- files,
- functions,
- classes,
- services,
- dependencies.

---

## Git / Change Knowledge

Used to answer:

- what changed recently,
- which files changed,
- which commit introduced a line,
- whether an incident began after a deployment/change.

---

## Incident Knowledge

Used to answer:

- has something similar happened before,
- what caused it,
- how it was fixed,
- whether the previous fix is relevant.

---

## Documentation Knowledge

Later versions may retrieve:

- architecture docs,
- runbooks,
- README information,
- operational procedures.

RAG output must include source references whenever practical.

---

# 10. Initial Demo Application

SentinelOps needs a controlled application against which incidents can safely be reproduced.

A small demonstration application should eventually contain enough components to create realistic failures without making the project unnecessarily large.

A suitable demonstration application may contain:

```text
Frontend
Backend API
PostgreSQL
Redis
```

Possible logical features:

```text
Authentication
Products
Orders
Payments (simulated)
```

The exact demo application will be decided during implementation.

Real payment processing is not required.

External paid infrastructure should not be required for the first working version.

---

# 11. Supported Incident Types for the Core Version

The initial product should focus on a small set of reproducible incident categories.

Examples:

## Application Exception

Example:

```text
Null reference / uncaught application exception
```

Expected SentinelOps behavior:

- detect failure,
- retrieve stack trace,
- locate code,
- inspect change history,
- produce RCA,
- propose safe code fix.

---

## Configuration Failure

Example:

```text
incorrect environment variable
incorrect service configuration
```

Expected behavior:

- connect runtime failure to configuration,
- explain evidence,
- propose configuration remediation.

---

## Dependency Failure

Example:

```text
Redis unavailable
database unavailable
```

Expected behavior:

- identify external dependency,
- avoid incorrectly blaming application code,
- clearly state uncertainty and affected path.

---

## Bad Recent Code Change

Example:

A new commit introduces a runtime error.

Expected behavior:

- correlate incident timing with Git change,
- identify affected function,
- show relevant commit,
- propose fix.

These incident types are sufficient for early versions.

---

# 12. Security Component

Security investigation is a later module.

It must not block completion of the core incident-response pipeline.

Potential responsibilities:

- analyze suspicious authentication failures,
- analyze unusual endpoint usage,
- group suspicious application events,
- retrieve relevant application context,
- alert developers.

The project must not market this module as a replacement for a network firewall, WAF, SIEM, EDR, or professional security monitoring system.

Dangerous autonomous security actions are outside the initial scope.

---

# 13. Daily Report

A later reporting module can produce a daily reliability summary.

Possible content:

```text
availability
incident count
incident severity
resolved incidents
unresolved incidents
root causes
remediation status
security events
important application errors
```

Possible delivery:

```text
dashboard
email
Slack
```

Only one delivery mechanism needs to be implemented initially.

---

# 14. User Interface

The UI should help the developer understand the incident rather than look visually complex.

Important screens eventually include:

## Incident List

Shows:

```text
incident
time
service
severity
status
```

## Incident Detail

Shows:

```text
what happened
runtime evidence
relevant logs
relevant code
recent changes
previous similar incidents
AI root-cause hypothesis
confidence
proposed solution
```

## Approval View

Allows developer to:

```text
approve
reject
request another investigation / edit
```

## Validation View

Shows:

```text
branch
changed files
build result
test result
incident reproduction result
regression result
```

UI should be developed only after the backend capabilities needed for a screen exist.

---

# 15. Expected End-State

A successful SentinelOps demonstration should eventually look like this:

```text
1. Demo application is running normally.

2. A controlled code/configuration problem is introduced.

3. Application starts failing.

4. Monitoring detects the incident.

5. SentinelOps opens an incident automatically or from the monitor event.

6. SentinelOps collects relevant evidence.

7. LangGraph investigation runs.

8. SentinelOps identifies:
   - affected service,
   - affected function/file,
   - runtime evidence,
   - relevant Git change,
   - root-cause hypothesis.

9. SentinelOps proposes a remediation.

10. Developer sees the evidence and approves.

11. SentinelOps creates:
    sentinel/incident-<id>-fix

12. AI applies the change in the isolated branch.

13. Build/tests run.

14. Incident conditions are reproduced.

15. SentinelOps shows whether the failure still occurs.

16. Developer makes the final merge decision.

17. Incident, investigation, solution, and result are saved as historical memory.

18. A future similar incident can retrieve the previous incident.
```

---

# 16. Explicit Non-Goals for Initial Development

Do not implement these until the core system is stable:

- predictive failure forecasting,
- machine-learning failure prediction,
- automatic production deployment,
- automatic merge to main,
- fully autonomous infrastructure mutation,
- multi-cloud support,
- complex Kubernetes remediation,
- enterprise RBAC,
- enterprise SSO,
- billing,
- mobile applications,
- custom LLM training,
- large-scale distributed event streaming,
- dozens of specialized agents,
- full SIEM/firewall replacement,
- production-grade SOC automation.

---

# 17. Implementation Stages

Each stage must produce something that the user can observe or verify.

The coding agent must never implement multiple future stages merely because they are documented here.

---

## Stage 0 — Repository Foundation and Development Controls

### Goal

Create the project skeleton and governance files without implementing SentinelOps functionality.

### Expected Visible Result

The user can open the repository and clearly see:

- organized folder structure,
- README,
- environment template,
- project journal,
- test setup,
- basic backend startup,
- health endpoint.

Example:

```text
GET /health

{
  "status": "ok",
  "service": "sentinelops"
}
```

### Gate

User confirms the repository starts correctly and the structure is understandable.

---

## Stage 1 — Incident Management Core

### Goal

Create the basic Incident domain and API.

### Expected Visible Result

The user can:

- create an incident,
- list incidents,
- open a specific incident,
- update basic incident status.

No AI is required yet.

### Gate

User manually tests the API/UI behavior and approves it.

---

## Stage 2 — Demo Application

### Goal

Create a controlled demo application for SentinelOps to monitor.

### Expected Visible Result

The demo application:

- starts normally,
- exposes a few endpoints,
- uses structured logging,
- includes at least one safe controlled failure mode.

### Gate

User confirms normal behavior and manually triggers the controlled failure.

---

## Stage 3 — Telemetry and Evidence Collection

### Goal

Connect runtime observations to SentinelOps incidents.

### Expected Visible Result

When the controlled failure occurs, SentinelOps can collect and display relevant evidence such as:

- timestamp,
- error log,
- stack trace,
- endpoint,
- service.

No root-cause LLM reasoning yet.

### Gate

User triggers an incident and verifies that the correct evidence is attached.

---

## Stage 4 — Repository / Source-Code Indexing

### Goal

Allow SentinelOps to understand and retrieve relevant source-code context.

### Expected Visible Result

Given a file/function/error reference, SentinelOps can retrieve relevant code chunks with source paths.

Example:

```text
Query:
OrderService checkout error

Results:
demo_app/services/order_service.py
lines ...
```

### Gate

User runs several retrieval queries and confirms results are relevant.

---

## Stage 5 — Git Change Intelligence

### Goal

Provide recent-code-change context for investigations.

### Expected Visible Result

For an incident or file, SentinelOps can show:

- recent commits,
- changed files,
- commit metadata,
- relevant diff/change summary.

### Gate

User creates a known code change and confirms SentinelOps identifies it correctly.

---

## Stage 6 — First LangGraph Investigation Workflow

### Goal

Combine incident evidence, source-code retrieval, and Git history.

### Expected Visible Result

For the controlled incident, SentinelOps produces an evidence-based RCA containing:

```text
what happened
probable cause
affected file/function
supporting evidence
relevant recent change
confidence
uncertainties
```

No automatic patching yet.

### Gate

User compares the RCA with the intentionally introduced problem and confirms correctness.

---

## Stage 7 — Incident Memory and Historical RAG

### Goal

Store resolved incident knowledge and retrieve similar incidents.

### Expected Visible Result

After one incident is marked resolved, a new related incident can retrieve the previous incident and explain why it is relevant.

### Gate

User reproduces two similar incidents and verifies historical retrieval.

---

## Stage 8 — Remediation Proposal

### Goal

Generate a proposed fix without modifying the repository.

### Expected Visible Result

The user sees:

```text
proposed fix
affected files
reason
risk
expected effect
patch preview
```

The repository remains unchanged.

### Gate

User verifies that proposed patches are understandable and safe.

---

## Stage 9 — Human Approval and Isolated Git Branch

### Goal

Introduce the first write action.

### Expected Visible Result

Only after explicit approval:

```text
sentinel/incident-<id>-fix
```

is created and the approved patch is applied there.

`main` must remain unchanged.

### Gate

User verifies branch isolation and code changes.

---

## Stage 10 — Automated Validation

### Goal

Determine whether the proposed remediation actually solves the incident.

### Expected Visible Result

SentinelOps reports:

```text
build status
test results
incident reproduction
regressions
validation summary
```

### Gate

User verifies results manually.

---

## Stage 11 — Developer Dashboard

### Goal

Provide a coherent UI over the stable backend capabilities.

### Expected Visible Result

User can navigate:

```text
Incident List
Incident Details
Evidence
RCA
Proposed Fix
Approval
Validation
```

### Gate

User performs the complete supported workflow from the UI.

---

## Stage 12 — Notifications

### Goal

Notify developers when important incidents occur.

### Expected Visible Result

At least one supported channel sends a useful incident notification.

Examples:

```text
email
Slack
```

### Gate

User receives and verifies the notification.

---

## Stage 13 — Runtime Security Investigation

### Goal

Analyze selected suspicious application-level events.

### Expected Visible Result

A controlled suspicious event produces:

```text
security event
supporting logs
context
risk classification
developer alert
```

No dangerous autonomous response.

### Gate

User verifies the event and explanation.

---

## Stage 14 — Daily Reliability Report

### Goal

Generate an understandable summary of the application's daily operational history.

### Expected Visible Result

Report includes available data such as:

```text
incidents
severity
root causes
resolution status
security events
important failures
```

### Gate

User verifies report correctness against stored incidents.

---

## Stage 15 — Hardening and Final Integration

### Goal

Make the complete approved workflow reliable.

Activities may include:

- regression tests,
- failure handling,
- retry policies,
- timeout handling,
- configuration cleanup,
- logging cleanup,
- documentation,
- final demo scenarios.

### Expected Visible Result

A complete end-to-end demonstration succeeds reliably.

---

# 18. Stage Completion Report Format

At the end of every implementation stage, the coding agent must respond using this structure:

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
10. What you should observe
11. Manual verification steps
12. Known limitations
13. Project journal updated: YES/NO
14. Ready for user verification

STOP.
Do not start the next stage.
```

---

# 19. Rules for Errors During Development

If a stage fails:

1. Do not hide the error.
2. Do not start another stage.
3. Record the error in the journal.
4. Identify the smallest likely cause.
5. Fix only what is necessary.
6. Re-run the stage's tests.
7. Re-run relevant regression tests.
8. Explain what changed.
9. Wait for user verification.

---

# 20. Rules for Refactoring

Refactoring is allowed only when:

- it is necessary for the active stage,
- existing behavior is preserved,
- relevant tests exist,
- the reason is documented.

Large "cleanup" refactors should not be mixed into feature stages.

If major refactoring becomes necessary, it should become its own user-approved stage.

---

# 21. Rules for Dependencies

Before adding a dependency, the coding agent should ensure:

- it serves a real requirement,
- an existing dependency does not already provide the capability,
- it is actively maintained,
- the project does not become unnecessarily dependent on a paid service.

All dependencies must be documented.

Secrets and API keys must never be committed.

Use environment variables and `.env.example`.

---

# 22. Testing Philosophy

Tests must grow with the project.

The project should eventually contain:

```text
unit tests
integration tests
workflow tests
retrieval tests
Git-operation tests
incident lifecycle tests
remediation safety tests
regression tests
```

Critical safety behavior must be tested.

Examples:

```text
AI cannot modify main without approval.
Rejected remediation does not modify repository.
Failed validation is clearly reported.
Missing telemetry does not produce a fake confident RCA.
```

---

# 23. AI Safety / Reliability Rules

The coding implementation and SentinelOps runtime should follow these rules.

SentinelOps must not:

- fabricate logs,
- fabricate Git commits,
- fabricate tests,
- fabricate source-code locations,
- claim a fix passed when a command failed,
- claim certainty without supporting evidence.

When information is insufficient, report:

```text
Insufficient evidence
```

rather than inventing a confident conclusion.

---

# 24. Definition of Core MVP

The core MVP is complete when Stages 0 through 10 work.

That means SentinelOps can demonstrate:

```text
incident
    ↓
evidence
    ↓
source code
    ↓
Git context
    ↓
AI RCA
    ↓
incident memory
    ↓
proposed fix
    ↓
human approval
    ↓
isolated branch
    ↓
automated validation
```

Stages after Stage 10 improve usability and breadth but are not required to prove the central idea.

---

# 25. Final Product Statement

SentinelOps is an AI-assisted incident investigation and recovery platform that connects production runtime evidence with source code, Git history, and historical incidents.

It helps developers understand:

```text
What failed?
Where did it fail?
Why did it fail?
What evidence supports that conclusion?
Has this happened before?
What change could fix it?
Did the proposed fix actually solve the problem?
```

The system assists the developer throughout the process while preserving human control over code changes and production decisions.
