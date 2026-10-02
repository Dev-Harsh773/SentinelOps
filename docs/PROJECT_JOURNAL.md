# SentinelOps — Project Journal

This living journal documents engineering decisions, problem-solving history, and stage completion records across the lifecycle of SentinelOps.

---

## Stage 0 — Repository Foundation and Development Controls

### Objective
Establish a clean, modular, and testable project foundation for SentinelOps without introducing incident management, AI reasoning, RAG, databases, or external integrations. Verify that the backend starts, responds to `GET /health`, provides API documentation, and passes automated tests.

### Design Decision
- Selected FastAPI and Uvicorn for standard asynchronous API capabilities and auto-generated OpenAPI documentation.
- Chose standard library `dataclasses` and `os.getenv` for configuration management to avoid unnecessary dependency overhead (such as `pydantic-settings`) in Stage 0.
- Implemented an application factory pattern (`create_app`) and centralized router aggregation (`app/api/__init__.py`) to allow future stages to add endpoints without modifying the main entry point.
- Created empty architectural boundary packages with concise docstrings to define domain separation (incidents, telemetry, repository, retrieval, agents, workflows, remediation, validation, notifications, reports, storage) without dummy or unfinished code.
- Structured centralized logging via standard library `logging` to avoid arbitrary `print()` statements across future modules.

### Files Added / Changed
- `requirements.txt`: Minimal dependencies (`fastapi`, `uvicorn`, `httpx`, `pytest`).
- `.gitignore`: Ignore rules for Python byte-cache, virtual environments, `.env`, test cache, and OS/IDE metadata.
- `.env.example`: Template for environment variables (`APP_NAME`, `APP_ENV`, `LOG_LEVEL`, `HOST`, `PORT`).
- `app/__init__.py`: Application root package definition.
- `app/main.py`: Application factory, lifespan management, and router inclusion.
- `app/api/__init__.py`: Router aggregator.
- `app/api/health.py`: `GET /health` endpoint definition.
- `app/common/__init__.py`: Package definition for shared modules.
- `app/common/config.py`: Dataclass-based centralized configuration with default fallbacks.
- `app/common/logging.py`: Standard logging setup with uniform formatting and level configuration.
- `app/incidents/__init__.py`: Architectural boundary placeholder.
- `app/telemetry/__init__.py`: Architectural boundary placeholder.
- `app/repository/__init__.py`: Architectural boundary placeholder.
- `app/retrieval/__init__.py`: Architectural boundary placeholder.
- `app/agents/__init__.py`: Architectural boundary placeholder.
- `app/workflows/__init__.py`: Architectural boundary placeholder.
- `app/remediation/__init__.py`: Architectural boundary placeholder.
- `app/validation/__init__.py`: Architectural boundary placeholder.
- `app/notifications/__init__.py`: Architectural boundary placeholder.
- `app/reports/__init__.py`: Architectural boundary placeholder.
- `app/storage/__init__.py`: Architectural boundary placeholder.
- `tests/__init__.py`: Test package definition.
- `tests/test_health.py`: Pytest suite verifying status code and response payload of `/health`.
- `README.md`: Project documentation, stage status, installation, and run instructions.
- `docs/PROJECT_JOURNAL.md`: Initial journal entry.

### Problems Encountered
No significant implementation issues were encountered during this stage.

### Attempts
Not applicable as the initial implementation succeeded as planned.

### Final Solution
Created the modular skeleton, verified imports and startup, and executed automated tests using `TestClient`.

### Why It Worked
The clean separation between routing, configuration, and application instantiation ensured straightforward initialization without circular dependencies.

### Verification
- Executed `pytest` across the repository; all tests passed with 100% success.
- Verified `GET /health` returns HTTP 200 and payload `{"status": "ok", "service": "sentinelops"}`.
- Verified `/docs` OpenAPI schema generation.

### Known Limitations
- No incident models, persistence, or telemetry ingestion are implemented.
- Configuration only handles basic application metadata and network bindings.
- All domain modules are empty architectural placeholders.

### User Approval
Approved

---

## Stage 1 — Incident Management Core

### Objective
Create the initial Incident domain and API allowing creation, listing, retrieval, and lifecycle status updates for incidents using an in-memory repository. Ensure strict lifecycle validation, UTC timezone-aware timestamps, clean interface abstraction, and complete test isolation without introducing databases, AI, RAG, or external monitoring.

### Design Decision
- Decoupled domain business logic and storage: established an abstract `IncidentRepository` and implemented `InMemoryIncidentRepository` backed by a dictionary. This guarantees future database persistence can be swapped in without modifying domain or API code.
- Embedded lifecycle protection in `IncidentService`: strictly permitted `OPEN → INVESTIGATING`, `OPEN → RESOLVED`, `INVESTIGATING → RESOLVED`, and `RESOLVED → CLOSED`, while rejecting invalid/backward transitions such as `CLOSED → any state`, `RESOLVED → OPEN`, `OPEN → CLOSED`, and `INVESTIGATING → CLOSED` with HTTP 400.
- Implemented robust input validation in Pydantic schemas using trimmed whitespace verification to reject empty-after-trim fields.
- Used UUID4 for non-sequential, unique incident identifiers and timezone-aware UTC timestamps (`datetime.now(timezone.utc)`).
- Bound one shared `InMemoryIncidentRepository` instance in `app/incidents/dependencies.py` to persist data during server runtime across requests, providing a dedicated `clear()` method for test fixture isolation.

### Files Added / Changed
- `app/incidents/models.py`: Domain dataclass `Incident`, `Severity` enum, `IncidentStatus` enum.
- `app/incidents/schemas.py`: Pydantic schemas for incident creation, status updating, and serialization.
- `app/incidents/repository.py`: `IncidentRepository` abstract base class and `InMemoryIncidentRepository`.
- `app/incidents/service.py`: `IncidentService` orchestrating business rules, UUID generation, timestamps, and transition validation, plus domain exception types.
- `app/incidents/dependencies.py`: Dependency injection providers for shared repository and service.
- `app/incidents/routes.py`: FastAPI endpoints for `POST /incidents`, `GET /incidents`, `GET /incidents/{id}`, and `PATCH /incidents/{id}/status`.
- `app/api/__init__.py`: Registered `incidents_router` with `api_router`.
- `tests/test_incidents.py`: Automated tests covering incident creation, validation, listing, retrieval, lifecycle transitions, invalid transition rejection, and missing incident 404 handling.
- `README.md`: Updated to Stage 1 documentation including endpoint descriptions, curl examples, and in-memory storage notes.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 0 status to Approved and added Stage 1 entry.

### Problems Encountered
No significant implementation issues were encountered during this stage.

### Attempts
Not applicable as the implementation proceeded according to plan with all tests passing on initial run.

### Final Solution
Separated repository interface from in-memory implementation, centralized lifecycle rules within `IncidentService`, wired routes into aggregated `api_router`, and verified all lifecycle transitions and validations via automated pytest suite.

### Why It Worked
Strict adherence to single-responsibility modules and interface-based repository design allowed rapid development, clear error translation to HTTP status codes, and deterministic test isolation.

### Verification
- Executed `pytest -v` running 11 test cases across `test_health.py` and `test_incidents.py`; all 11 tests passed in 0.48s.
- Programmatically verified that `GET /health` continues returning HTTP 200 `{"status": "ok", "service": "sentinelops"}` (Stage 0 backward compatibility preserved).
- Verified Swagger OpenAPI UI generation at `/docs` reflecting all incident endpoints.
- Verified creation, listing, retrieval, valid transition, and invalid transition rejection behaviors.

### Known Limitations
- Storage is in-memory only; all incidents are reset when the application process terminates or restarts.
- No pagination or filtering is implemented for `GET /incidents`.
- No telemetry, evidence attachment, AI reasoning, RAG, or notification capabilities exist yet.

### User Approval
Approved

---

## Stage 2 — Controlled Demo Application

### Objective
Create a standalone, controlled e-commerce demo application (`demo_app`) that operates independently from SentinelOps. The application serves realistic endpoints (catalog and orders), logs structured messages with request correlation IDs, contains an intentional, reversible failure mode (`order_processing_error`), and provides administrative failure toggles without telemetry or AI integration.

### Design Decision
- Complete architectural isolation: Built `demo_app` in a dedicated directory with its own config, logging, and FastAPI instance configured for port 8001, leaving SentinelOps completely untouched on port 8000.
- Single source of truth for exceptions: Placed `OrderProcessingError` and `ProductNotFoundError` in `demo_app/services/exceptions.py`.
- Clean route/exception handling: Kept `POST /orders` thin by letting `OrderProcessingError` bubble up to a global FastAPI exception handler that logs traceback with correlation ID and emits HTTP 500 without leaking internal code traces to clients.
- Pre-failure validation: Verified product existence before checking the failure flag, ensuring invalid products return HTTP 404 rather than 500 even during active failure mode.
- Request correlation middleware: Generated UUID request ID, attached it to `request.state.request_id`, included it in request/response/error logs, and emitted `X-Request-ID` in all response headers (including 500 failure responses).
- Integer minor currency units: Modeled product prices and order totals strictly as integers (e.g. 2499 for 24.99) to avoid floating-point math issues.
- Health independence: Guaranteed `GET /health` on `demo_app` remains HTTP 200 even while order processing is failing, modeling partial business degradation.

### Files Added / Changed
- `demo_app/__init__.py`: Package root.
- `demo_app/common/config.py`: Demo app settings (`DEMO_APP_PORT=8001`, `DEMO_APP_NAME="demo-app"`).
- `demo_app/common/logging.py`: Structured logger configuration.
- `demo_app/common/__init__.py`: Package init.
- `demo_app/services/exceptions.py`: Centralized domain exceptions (`OrderProcessingError`, `ProductNotFoundError`).
- `demo_app/failure_modes/controller.py`: Singleton failure controller with enable/disable/status methods and test-only reset.
- `demo_app/failure_modes/__init__.py`: Package init.
- `demo_app/models/schemas.py`: Pydantic schemas for `Product`, `OrderCreateRequest`, `OrderResponse`, and `FailureStatusResponse`.
- `demo_app/models/__init__.py`: Package init.
- `demo_app/services/product_service.py`: Static in-memory catalog service.
- `demo_app/services/order_service.py`: Order placement and controlled failure trigger service.
- `demo_app/services/__init__.py`: Package init.
- `demo_app/api/products.py`: Catalog listing and retrieval endpoints.
- `demo_app/api/orders.py`: Order creation endpoint.
- `demo_app/api/admin.py`: Development failure toggles (`/admin/failures`).
- `demo_app/api/__init__.py`: Aggregated router for demo app.
- `demo_app/main.py`: Demo FastAPI application with correlation middleware and 500 exception handler.
- `tests/demo_app/__init__.py`: Package init.
- `tests/demo_app/conftest.py`: Fixtures for test client and failure state reset.
- `tests/demo_app/test_demo_health.py`: Health endpoint and request ID header verification.
- `tests/demo_app/test_products.py`: Product catalog retrieval and 404 tests.
- `tests/demo_app/test_orders.py`: Order creation, total calculation, and validation tests.
- `tests/demo_app/test_failures.py`: Failure toggle endpoints, full failure/recovery lifecycle test, and pre-failure product validation test.
- `README.md`: Updated to Stage 2 with clear separation between SentinelOps (port 8000) and Demo App (port 8001).
- `docs/PROJECT_JOURNAL.md`: Updated Stage 1 status to Approved and added Stage 2 entry.

### Problems Encountered
No significant implementation issues were encountered during this stage.

### Attempts
Not applicable as the implementation followed the refined architectural plan and passed all 21 automated tests on initial execution.

### Final Solution
Implemented isolated demo application on port 8001 with centralized exceptions, thin routes, correlation middleware, and dedicated pytest suites in `tests/demo_app/`.

### Why It Worked
Strict separation between SentinelOps and demo application prevented architectural coupling, and clean exception handling ensured deterministic failure and recovery.

### Verification
- Executed `pytest -v` running 21 tests across SentinelOps and Demo App suites; all 21 passed in 1.01s.
- Verified request correlation `X-Request-ID` is returned in both 201 Created and 500 Internal Server Error responses.
- Verified controlled failure lifecycle: normal order (201) -> enable failure -> order fails (500) while health remains 200 -> disable failure -> order succeeds (201).
- Verified missing product returns 404 even while failure mode is active.
- Confirmed zero regression on SentinelOps Stage 0 and Stage 1 tests.

### Known Limitations
- Demo application data is held in-memory; orders and failure mode states reset on application restart.
- Failure modes are currently limited to `order_processing_error`.
- No automatic log collection or telemetry forwarding to SentinelOps exists yet.

### User Approval
Approved

---

## Stage 3 — Telemetry and Evidence Collection

### Objective
Connect runtime failures in the demo application to SentinelOps incidents by establishing structured JSONL runtime event emission in `demo_app` and an Evidence collection pipeline in SentinelOps. Enable manual collection of failure evidence by request ID without automated incident creation, AI interpretation, or source-code indexing.

### Design Decision
- JSONL runtime log source: Implemented `JsonlEventLogger` in `demo_app` appending uniform JSON events to `runtime/demo_app.jsonl` (configured via `DEMO_APP_LOG_PATH`), preserving existing console logging untouched.
- Clean separation between collector and business service:
  - `RuntimeLogCollector` remains generic: reads files, safely parses JSON lines, strictly converts timestamps to timezone-aware UTC datetimes, skips malformed lines, and filters by `request_id`.
  - `TelemetryService` applies domain filtering: selects evidence-worthy events (e.g. `order_processing_failed` and ERROR-level events) and ignores routine lifecycle noise (`request_received`, `request_completed`).
- First-class `exception_type`: Added directly to `Evidence` domain model and schemas, keeping raw tracebacks cleanly inside `metadata`.
- Temporal distinction: Preserved original runtime event occurrence time as `timestamp` (UTC) while recording SentinelOps ingestion time as `created_at`.
- Logical source identity: Decoupled evidence source representation (`source="demo-app-runtime-log"`) from machine-specific filesystem paths.
- Event-level deduplication: Implemented fingerprint hashing (`incident_id|source|request_id|event|timestamp|exception_type`) so duplicate collection attempts for the same request ID return `collected=0` with a clean explanation without duplicating records.
- Controlled edge handling: Non-existent incidents return HTTP 404, unknown request IDs return HTTP 200 with `collected=0`, and missing log files return HTTP 200 with `collected=0` and a clear message rather than unhandled 500 errors.
- Incident lifecycle protection: Strictly preserved incident status during evidence collection without automatic transitions.
- Isolated test suite: Employed FastAPI `dependency_overrides` and temporary pytest paths (`tmp_path`) so tests never touch or pollute the development `runtime/demo_app.jsonl`.

### Files Added / Changed
- `runtime/.gitkeep`: Track runtime directory in Git.
- `.gitignore`: Ignored `runtime/*.jsonl` generated log files.
- `.env.example`: Added `DEMO_APP_LOG_PATH=runtime/demo_app.jsonl`.
- `app/common/config.py`: Added `demo_app_log_path` to `AppConfig`.
- `demo_app/common/config.py`: Added `log_file_path` to `DemoAppConfig`.
- `demo_app/common/event_logger.py`: Implemented `JsonlEventLogger` with consistent JSON schema formatting.
- `demo_app/main.py`: Integrated JSONL event emission in correlation middleware and 500 exception handler.
- `demo_app/api/orders.py`: Emitted `order_created` events upon successful order placement.
- `demo_app/api/admin.py`: Emitted `failure_mode_enabled` and `failure_mode_disabled` events.
- `app/telemetry/models.py`: Created `Evidence` domain dataclass with `exception_type`, `EvidenceType`, and internal fingerprinting.
- `app/telemetry/schemas.py`: Created `EvidenceCollectRequest`, `EvidenceResponse`, and `EvidenceCollectionResponse`.
- `app/telemetry/repository.py`: Created `EvidenceRepository` interface and `InMemoryEvidenceRepository`.
- `app/telemetry/collector.py`: Created generic `RuntimeLogCollector` with safe JSON parsing and UTC timestamp conversion.
- `app/telemetry/service.py`: Created `TelemetryService` with failure event selection, deduplication, and incident validation.
- `app/telemetry/dependencies.py`: Created dependency injection providers for telemetry components.
- `app/telemetry/routes.py`: Created `POST /incidents/{incident_id}/evidence/collect` and `GET /incidents/{incident_id}/evidence`.
- `app/api/__init__.py`: Registered `telemetry_router` with `api_router`.
- `tests/test_telemetry.py`: Added 11 automated tests covering JSONL emission, evidence collection, noise filtering, deduplication, missing incident 404s, unknown request IDs, missing log files, and malformed log handling.
- `tests/demo_app/conftest.py`: Updated fixtures to isolate event logging to `tmp_path`.
- `README.md`: Documented Stage 3 telemetry workflow, evidence collection endpoints, and PowerShell verification commands.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 2 to Approved and added Stage 3 entry.

### Problems Encountered
During initial test suite execution, monkeypatching of the log collector was bypassed by FastAPI's dependency injection container, causing collector tests to read from the default file path and fail deduplication assertions.

### Attempts
Attempted standard `monkeypatch.setattr` on module functions.

### Final Solution
Switched to FastAPI's built-in `app.dependency_overrides[get_log_collector]` mechanism in pytest fixtures, ensuring test isolation and exact dependency injection resolution.

### Why It Worked
FastAPI evaluates dependencies via internal provider functions; `dependency_overrides` cleanly replaces the provider during request dispatch across all routes.

### Verification
- Executed `pytest -v` running 32 tests across Stage 0, Stage 1, Stage 2, and Stage 3; all 32 passed in 1.54s with zero regressions.
- Verified that given `request_received`, `order_processing_failed`, and `request_completed`, only `order_processing_failed` is converted into Incident Evidence.
- Verified that repeating evidence collection with the same `request_id` returns `collected=0` with message `"Matching evidence was already attached to this incident."` and prevents duplication.
- Verified that unknown request IDs and missing log files return HTTP 200 with `collected=0` and appropriate messages without raising 500 errors.
- Verified that incident status remains unaffected during evidence collection.

### Known Limitations
- Evidence collection is entirely manual; SentinelOps does not automatically detect failures or tail logs.
- Evidence storage is in-memory only.
- Evidence types are currently limited to `runtime_log`.
- No AI reasoning, RAG, or root-cause analysis is performed yet.

### User Approval
Approved

---

## Stage 4 — Repository / Source-Code Indexing

### Objective
Provide deterministic, lexical source-code scanning, AST parsing, chunking, indexing, and ranked retrieval for the demo application repository in SentinelOps. Enable answering queries such as `"order processing failure"` or `"OrderService.create_order"` with relevant, non-overlapping code chunks without AI embeddings, vector databases, LLMs, or Git commit history analysis.

### Design Decision
- Target Isolation: Configured scanning strictly for Python source files in `demo_app` via `SOURCE_REPOSITORY_PATH=demo_app`. Excluded directories include `tests/`, `runtime/`, `.git/`, `__pycache__/`, and virtual environments.
- Deterministic Chunk Fingerprints: Derived chunk IDs (`chunk-<sha256>`) deterministically from `(file_path, symbol_name, symbol_type, start_line, end_line)`, ensuring unchanged code generates identical chunk identifiers across reindexing runs.
- Non-Overlapping AST Chunking:
  - Top-level function chunks preserve preceding decorators (e.g. `@router.post(...)`), starting at the first decorator line.
  - Class chunks capture the class header, docstring, and class attributes up to the first method definition, avoiding whole-class body duplication across methods.
  - Method chunks are extracted individually with qualified names (`ClassName.method_name`).
  - Module chunks capture top-level statements, imports, constants, and module docstrings outside function/class line intervals.
- Lexical Tokenization: Split code tokens across camelCase, PascalCase, snake_case, path segments, and punctuation (`OrderProcessingError` -> `order`, `processing`, `error`).
- Lexical Scoring Hierarchy:
  - Exact symbol match (highest, +50.0)
  - Symbol token matches (high, +10.0 per token, +15.0 full coverage bonus)
  - File path token matches (medium, +3.0 per token)
  - Content token matches (base, +1.0 per token with term-frequency dampening)
  - Full-query content substring match bonus (+5.0)
- Deterministic Tie-Breaking: Ranked results by `(-score, file_path, start_line)`.
- Strict Relevance Threshold: Nonsense queries (e.g. `"quantum banana spaceship"`) score 0.0, falling below `MIN_RELEVANCE_SCORE = 1.0` and returning `results: []`.
- Atomic Indexing: Index rebuild replaces the entire in-memory chunk snapshot in a single lock acquisition, preventing partial or duplicated chunk states.
- Clean Architecture Separation: `RetrievalService` contains zero HTTP or framework-level dependencies, raising domain exceptions `RepositoryNotFoundError` and `RepositoryNotIndexedError`, mapped in routes to HTTP 400 and HTTP 409.
- POSIX-Normalized Paths: All chunk file paths are formatted as relative POSIX paths (`demo_app/...`) without Windows backslashes or drive letters.

### Files Added / Changed
- `.env.example`: Added `SOURCE_REPOSITORY_PATH=demo_app`.
- `app/common/config.py`: Added `source_repository_path: str` to `AppConfig`.
- `app/retrieval/models.py`: Created `CodeChunk` domain dataclass with deterministic factory and `IndexStatus`.
- `app/retrieval/scanner.py`: Created `SourceScanner` with directory filtering, POSIX path normalization, and deterministic ordering.
- `app/retrieval/parser.py`: Created `PythonAstParser` with decorator preservation, method de-duplication, module chunking, and line trimming.
- `app/retrieval/index.py`: Created code tokenizer, `CodeIndex` in-memory storage, scoring engine, and `RepositoryNotIndexedError`.
- `app/retrieval/schemas.py`: Created Pydantic models for index summary, index status, validated search request (`1 <= limit <= 20`), and search response.
- `app/retrieval/service.py`: Created framework-independent `RetrievalService`.
- `app/retrieval/dependencies.py`: Created dependency injection provider for shared `CodeIndex` and `RetrievalService`.
- `app/retrieval/routes.py`: Created `POST /repository/index`, `GET /repository/status`, and `POST /repository/search`.
- `app/retrieval/__init__.py`: Exported public retrieval domain symbols.
- `app/api/__init__.py`: Registered `repository_router` in application router.
- `tests/test_retrieval.py`: Created 15 automated unit and integration tests for scanner, parser, tokenizer, error resilience, status lifecycle, search, validation, and atomicity.
- `README.md`: Updated to Stage 4 with index/search API documentation and verification examples.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 3 to Approved and added Stage 4 entry.

### Problems Encountered
1. In generic failure queries such as `"order processing failure"`, utility/admin toggle functions (`enable_order_processing_failure`, `FailureModeController.enable_order_processing_error`) initially ranked above the core execution-path business method (`OrderService.create_order`). This occurred because the admin functions' long symbol names repeated multiple query words without document-frequency or length normalization, while implementation content was underweighted relative to symbol token matches.

### Attempts
1. Initially expanded search limit to 10 to include `order_service.py` in downstream results. However, this did not solve the fundamental ranking invertedness: the runtime execution path where the error is raised should naturally rank ahead of administrative test controls for incident-oriented queries.
2. Experimented with lightweight document frequency (IDF) and implementation weighting without external NLP dependencies.

### Final Solution
Implemented a general, deterministic lexical ranking refinement in `CodeIndex`:
- **Document Frequency (IDF) Awareness**: Precomputed token document frequencies across the indexed corpus; tokens that appear widely across many chunks (e.g. `order`, `failure`) contribute proportionally less than distinctive tokens via standard smoothed IDF: `log((N + 1) / (df + 1)) + 1.0`.
- **Symbol Length Normalization**: Scaled partial symbol token matches by symbol precision (`len(matched_tokens) / len(symbol_tokens)`), preventing long administrative symbol names from inflating scores simply by accumulating multiple query tokens.
- **Dominant Exact Symbol Boost**: Kept exact symbol matches dominant (`+100.0` for full qualified match, `+75.0` for unqualified match) ensuring symbol lookups like `OrderService.create_order` or `OrderProcessingError` unconditionally rank first.
- **Implementation Content Weighting**: Applied TF-IDF scoring on content (`(1.0 + log(1 + count)) * idf`), rewarded query concept coverage in the implementation body, and added runtime exception-site detection (recognizing `raise <Exception>` where the raised exception shares concepts with the query, such as `raise OrderProcessingError`).
- **Zero Hardcoding**: Did not hardcode any file names, paths, or directory boosts. The ranking logic is entirely general.

### Verification
- Executed `pytest -v` across all 48 test cases; all 48 tests passed in 1.66s with 100% pass rate.
- Added `test_retrieval_quality_execution_path_ranks_above_admin_controls` verifying on an isolated repository that an execution method raising an error ranks above administrative toggles.
- Verified that `POST /repository/search` for `"order processing failure"` ranks `OrderService.create_order` at rank 1 (score 131.29) ahead of administrative toggles.
- Verified query `"OrderService.create_order"` continues to rank `OrderService.create_order` at rank 1 with dominant score (223.86).
- Verified query `"OrderProcessingError"` ranks the `OrderProcessingError` exception class first (score 159.45).
- Verified nonsense query `"quantum banana spaceship"` returns `total: 0, results: []`.
- Verified HTTP 409 when unindexed, deterministic chunk IDs, and POSIX path normalization remain intact.

### Known Limitations
- Lexical keyword and token-based search only; no semantic embeddings or vector indexing.
- Retrieval results are not yet attached to incidents.
- No Git commit history or blame analysis is performed.
- No AI or LLM root-cause analysis is performed yet.

### User Approval
Approved

---

## Stage 5 — Git Change Intelligence

### Objective
Provide SentinelOps with deterministic, read-only local Git repository inspection capabilities to answer factual questions regarding recent commits, commit details, changed files, unified diffs, and single-file modification histories without external GitHub APIs, tokens, or automated incident causality assertions.

### Design Decision
- Pure Read-Only Local Execution: Standard library `subprocess.run` with `shell=False`, argument arrays (`["git", "-C", repo_path, ...]`), and a strict 10-second timeout. Completely avoids mutations (`checkout`, `commit`, `push`, `reset`, `branch`, etc.).
- Layered Architecture Separation:
  - `GitClient`: Isolated subprocess execution, machine-readable output parsing, and low-level Git commands (`rev-parse`, `log`, `diff-tree`).
  - `GitService`: Domain business logic, commit hash regex validation (`^[0-9a-fA-F]{7,40}$`), repository-relative path traversal validation, and diff truncation limits. Free of FastAPI or HTTP imports.
  - FastAPI Routes: Mapping domain exceptions to explicit HTTP status codes (`GitRepositoryNotFoundError` -> 500, `GitRepositoryInvalidError` -> 500, `GitCommitNotFoundError` -> 404, `GitFilePathInvalidError` -> 400).
- Explicit Logical Repository Identity: Exposed `repository="sentinelops"` across API responses, preventing leakage of physical host filesystem paths.
- Machine-Readable Parsing & Root-Commit Support:
  - Formatted commit logs with `%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%B%x1e` using ASCII unit (`\x1f`) and record (`\x1e`) separators.
  - Handled root commits (commits without parents) via `git diff-tree --root -r --no-commit-id -z` for `--name-status`, `--numstat`, and textual patches (`-p`), supporting single-commit repositories seamlessly.
  - Used null-delimited (`-z`) parsing for `name-status` and `numstat`, properly associating additions/deletions with renamed (`R`), copied (`C`), added (`A`), modified (`M`), and deleted (`D`) files.
  - Parsed author and committer timestamps as timezone-aware ISO datetimes (`%aI`, `%cI`).
- Path Traversal & Deleted File Safety:
  - Enforced repository-relative POSIX paths, strictly rejecting directory traversal (`..`) and absolute drive/root paths.
  - Path validation does not require physical file presence (`Path.exists()`), allowing full historical inspection of deleted and renamed files.
- Bounded Diff Truncation:
  - Unified diffs capped at 50,000 characters, cleanly slicing on newline boundaries and reporting `"truncated": true` when exceeded.
- Test Isolation Guarantee:
  - Automated tests run exclusively against temporary Git repositories initialized in `tmp_path`, verifying root commits, multi-commit history, renames, deletions, diffs, and validation without mutating the active project repository.

### Files Added / Changed
- `.env.example`: Added `GIT_REPOSITORY_PATH=.`.
- `app/common/config.py`: Added `git_repository_path: str` to `AppConfig`.
- `app/repository/models.py`: Created `GitCommit`, `ChangedFile`, `CommitDetails`, `CommitDiff`, and domain exception classes.
- `app/repository/client.py`: Created `GitClient` with read-only subprocess execution and null-delimited format parsers.
- `app/repository/service.py`: Created `GitService` with commit/path validators and query orchestration.
- `app/repository/schemas.py`: Created Pydantic response models for commits, changed files, details, diffs, and file history.
- `app/repository/dependencies.py`: Created dependency injection providers for `GitService` and `GitClient`.
- `app/repository/routes.py`: Created endpoints for `GET /git/commits`, `GET /git/commits/{commit_hash}`, `GET /git/commits/{commit_hash}/diff`, and `GET /git/files/history`.
- `app/repository/__init__.py`: Exported public repository domain symbols.
- `app/api/__init__.py`: Registered `git_router` with application router.
- `tests/test_repository.py`: Created 17 unit and API integration tests covering repository validation, root commits, commit details, path-filtered diffs, renames, deleted file history, path traversal rejection, POSIX paths, and diff truncation.
- `README.md`: Updated to Stage 5 documentation with workflow commands, endpoint descriptions, and scope boundaries.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 4 to Approved and added Stage 5 entry.

### Problems Encountered
1. In `test_invalid_commit_format_rejected`, an initial assertion requested `GET /git/commits/..%2F..%2Fetc`. Starlette's HTTP router normalized the URL path before reaching the endpoint, returning 404 instead of dispatching to the commit endpoint and returning 400.
2. In initial Git diff-tree testing, root commits (such as the initial baseline commit `ea2797a`) required `--root` flag to generate diffs and changed file records against the empty tree.

### Attempts
1. Verified URL path resolution behavior in Starlette routing.
2. Tested `git diff-tree --root` on both root and non-root commits in temporary repositories.

### Final Solution
1. Updated commit format rejection test to use `GET /git/commits/invalid..hash` and `GET /git/commits/abc;rm`, which properly route to `/git/commits/{commit_hash}` and trigger `GitCommitReferenceInvalidError` -> HTTP 400.
2. Included `--root` in all `diff-tree` invocations in `GitClient`, providing uniform diff and changed-file behavior for both initial commits and subsequent commits.

### Why It Worked
`--root` instructs Git to treat root commits as diffs against the empty tree object, correctly enumerating all initial files as added with positive line counts.

### Verification
- Executed `pytest -v` across all 65 test cases; all 65 tests passed in 23.69s with 100% pass rate and zero regressions.
- Verified `GET /git/commits?limit=5` on the real SentinelOps repository correctly returns the baseline commit `ea2797a` with message `"Initial SentinelOps implementation through Stage 4"` and author metadata.
- Verified `GET /git/commits/ea2797a` returns 75 changed files with exact addition counts.
- Verified `GET /git/commits/ea2797a/diff` returns unified diff text with `"truncated": true` (due to initial repository size exceeding 50,000 characters).
- Verified `GET /git/files/history?path=demo_app/services/order_service.py&limit=10` returns the baseline commit.
- Verified Stage 4 search regression test (`POST /repository/search` with `"OrderService.create_order"`) continues to return `OrderService.create_order` as the top match.

### Known Limitations
- Local Git repository data only; no remote branch synchronization or pull request metadata.
- Textual unified diffs only; binary file modifications report metadata but omit diff content.
- Stage 5 does not perform automated incident causality analysis or commit blame linking.

### User Approval
Approved

---

## Stage 6 — First LangGraph / AI Investigation Workflow

### Objective
Introduce the first AI-assisted incident investigation workflow into SentinelOps by orchestrating deterministic services (Incident Management, Runtime Telemetry Evidence, Source-Code AST Retrieval, Git Change Intelligence) and LLM reasoning through LangGraph. Produce structured, evidence-grounded Root Cause Analyses (RCA) citing concrete evidence identifiers with bounded validation and revision loops, without performing code modifications, patch generation, branch creation, commits, merges, or deployments.

### Design Decision
- **LangGraph Multi-Node Orchestration**: Decomposed the investigation into discrete, single-responsibility nodes (`analyze_runtime`, `retrieve_code`, `analyze_code`, `retrieve_git_context`, `analyze_changes`, `synthesize_rca`, `validate_rca`, `revise_rca`) rather than relying on an unbounded monolithic prompt or autonomous tool execution.
- **Strict Separation of Deterministic Retrieval vs LLM Reasoning**: The LLM is never given direct access to the filesystem, shell commands, or Git. Retrieval is completely deterministic via `RetrievalService` and `GitService`; the retrieved structured context is passed cleanly into LLM reasoning nodes.
- **Structured Output Typing**: Defined typed Pydantic models and domain dataclasses (`RuntimeAnalysis`, `CodeAnalysis`, `ChangeAnalysis`, `RootCauseAnalysis`, `RCAValidation`, `Investigation`) ensuring robust parsing and predictable API contracts.
- **Concrete Evidence Grounding**: Enforced that supporting evidence citations in the RCA reference verified, concrete IDs: runtime evidence UUIDs, deterministic code chunk IDs (`chunk-<hash>`), and hexadecimal Git commit hashes.
- **Adversarial Validation & Bounded Revision**: Introduced a dedicated validation node that checks RCA claims against supplied evidence, detecting ungrounded claims or hallucinated external technologies (such as Redis or unprovided databases). Utilized LangGraph conditional routing to trigger a revision node with a strict upper bound (maximum 1 revision / 2 validation checks total) to eliminate infinite loops.
- **Pluggable LLM Provider & 100% Offline Testing**: Implemented `InvestigationLLM` protocol with `FakeInvestigationLLM` for deterministic, zero-cost, network-free local testing and `LangChainInvestigationLLM` for production OpenAI structured outputs via `ChatOpenAI.with_structured_output`. Wrapped provider errors in domain exceptions to prevent leaking API keys.
- **Fail-Safe Edge Handling**: Implemented graceful error recovery for empty evidence (HTTP 409 `NoEvidenceForInvestigationError`), non-existent incidents (HTTP 404), unindexed or empty code retrieval (proceeds with lower confidence and explicit uncertainty notes), and missing Git history.

### Files Added / Changed
- `requirements.txt`: Added `langgraph`, `langchain-core`, and `langchain-openai`.
- `.env.example`: Added `LLM_PROVIDER=mock`, `LLM_MODEL=gpt-4o-mini`, `OPENAI_API_KEY=`.
- `app/common/config.py`: Added `llm_provider`, `llm_model`, `openai_api_key`, `git_context_limit`, and `rca_max_revisions` to `AppConfig`, with `.env` file loading support.
- `app/agents/models.py`: Created domain models (`EvidenceReference`, `RuntimeAnalysis`, `CodeAnalysis`, `ChangeAnalysis`, `RootCauseAnalysis`, `RCAValidation`, `InvestigationStatus`, `Investigation`) and domain exceptions (`InvestigationNotFoundError`, `NoEvidenceForInvestigationError`, `InvestigationLLMError`). Enhanced `RootCauseAnalysis` with `failure_location` and `triggering_condition`.
- `app/agents/schemas.py`: Created Pydantic request/response schemas for investigation endpoints and structured LLM outputs, including `failure_location` and `triggering_condition`.
- `app/agents/prompts.py`: Created centralized system prompts distinguishing `symptom`, `failure_location`, `triggering_condition`, and `root_cause_hypothesis`, with explicit Git relevance qualification rules.
- `app/agents/llm.py`: Implemented `InvestigationLLM` protocol, deterministic `FakeInvestigationLLM` (with commit deduplication across files, regex-based triggering condition extraction, baseline Git commit exclusion from causal citations, and depth validation), and production `LangChainInvestigationLLM` (with commit deduplication and structured mapping).
- `app/workflows/investigation_state.py`: Created `InvestigationState` TypedDict for LangGraph state management.
- `app/workflows/investigation_graph.py`: Created LangGraph state machine with 8 nodes, conditional validation routing, and bounded revision loop.
- `app/agents/repository.py`: Created `InvestigationRepository` interface and `InMemoryInvestigationRepository`.
- `app/agents/service.py`: Created `InvestigationService` orchestrating input validation, graph execution, and persistence.
- `app/agents/dependencies.py`: Created FastAPI dependency injection providers, strictly enforcing no silent mock fallback when `LLM_PROVIDER=openai` without an API key (raises `InvestigationLLMError`).
- `app/agents/routes.py`: Created `POST /incidents/{incident_id}/investigate` and `GET /incidents/{incident_id}/investigation` with proper exception mapping and response formatting.
- `app/agents/__init__.py`: Exported public investigation symbols.
- `app/workflows/__init__.py`: Exported public workflow symbols.
- `app/api/__init__.py`: Registered `investigation_router` in `api_router`.
- `app/main.py`: Added global exception handler for `InvestigationLLMError` returning HTTP 502 Bad Gateway.
- `app/retrieval/index.py`: Added `clear()` method to `CodeIndex` for test isolation.
- `tests/test_investigation.py`: Created comprehensive 16-test suite covering graph happy path, evidence grounding preservation, unsupported claim detection, bounded revision, retry limits, 404/409 error handling, empty code/git recovery, zero network calls assertion, RCA depth & triggering condition verification, Git baseline citation omission, commit deduplication, and explicit OpenAI provider error handling.
- `README.md`: Updated to Stage 6 documentation with full manual demo workflow, corrected curl commands (`/admin/failures/order-processing/enable`, `/evidence/collect`), LLM configuration, and scope boundaries.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 5 to Approved and added comprehensive Stage 6 record.

### Problems Encountered
1. In `CodeIndex`, no `clear()` method existed to reset the in-memory index between isolated test runs, leading to `AttributeError: 'CodeIndex' object has no attribute 'clear'`.
2. In `app/agents/service.py`, `evidence_repository.get_by_incident()` was called instead of the interface method `list_for_incident()`, raising an `AttributeError`.
3. In `tests/test_investigation.py`, the 404 assertion checked for `"Incident '...' not found"` instead of matching the exact domain message format `"Incident with ID '...' not found."`.
4. Live testing identified shallow RCA outputs (naming the exception class rather than underlying triggering condition), baseline commits being cited as causal evidence, and multiple file references duplicating Git commits in change analysis.

### Attempts
1. Verified `CodeIndex` attributes and thread safety locking in `app/retrieval/index.py`.
2. Checked method definitions in `EvidenceRepository` in `app/telemetry/repository.py`.
3. Checked exception formatting in `IncidentNotFoundError` in `app/incidents/service.py`.
4. Analyzed causal chain representation and evidence relevance filtering across `FakeInvestigationLLM` and `LangChainInvestigationLLM`.

### Final Solution
1. Added thread-safe `clear()` method to `CodeIndex` to reset chunks, document frequencies, and index status.
2. Updated `InvestigationService.investigate` to call `list_for_incident(incident_id)`.
3. Updated the 404 test assertion to verify `unknown_id in res.json()["detail"] and "not found" in res.json()["detail"].lower()`.
4. Enriched RCA schema, prompts, and implementations to distinguish `symptom`, `failure_location`, `triggering_condition`, and `root_cause_hypothesis`.
5. Added commit hash deduplication across multiple files in `analyze_changes`.
6. Enforced that baseline/initial commits are retained in `git_context` and `change_analysis` but excluded from `supporting_evidence` (noted in `uncertainties`).
7. Added explicit `InvestigationLLMError` handling without mock fallback when `LLM_PROVIDER=openai` is missing an API key.

### Why It Worked
Thread-safe clearing ensures test independence, interface conformity ensures reliable repository interaction, causal depth separation prevents shallow RCA tautologies, commit deduplication eliminates redundant facts, and relevance filtering prevents baseline repository history from being falsely blamed.

### Real-Provider Reliability Fixes (OpenAI Provider Hardening)
- **Problem 1 (Cascading Reasoning Failure)**: When testing Stage 6 with a live OpenAI key (`gpt-4o-mini`), all reasoning stages failed: `runtime_analysis`, `code_analysis`, and `change_analysis` became `null`. The graph failed open into `synthesize_rca`, where the LLM hallucinated ungrounded symbols (`OrderService.checkout_order`) and unsupplied payload fields (`email`, `shipping_address`). Although the validator correctly marked the RCA invalid (`valid=False`), `InvestigationService` incorrectly marked the investigation `completed` because an RCA object existed.
- **Root Cause 1**:
  1. `LangChainInvestigationLLM.analyze_runtime` attempted to access `incident.description`. The `Incident` domain model has `summary`, not `description`, causing an uncaught `AttributeError`.
  2. In `investigation_graph.py`, LangGraph lacked fail-closed routing edges after `analyze_runtime` and `analyze_code`, allowing execution to continue into RCA synthesis with missing prerequisite analyses.
  3. `synthesize_rca_node` lacked defensive preconditions guarding against missing upstream reasoning.
  4. `InvestigationService.investigate` computed `status = InvestigationStatus.COMPLETED if rca else InvestigationStatus.FAILED`, ignoring `validation.valid`.
  5. Grounding checks were partially split between mock and real providers without a single shared deterministic grounding layer.
- **Problem 2 (RCA Synthesis NameError)**: Real OpenAI execution succeeded through runtime, code, and Git analysis but exposed a `NameError` in RCA synthesis (`RCA synthesis failed: Root cause analysis synthesis failed: NameError`).
- **Root Cause 2**:
  In `LangChainInvestigationLLM.synthesize_rca`, retrieved source code chunks were formatted into variable `chunks_context`, but the prompt construction f-string referenced `{chunks_text}`, triggering an undefined identifier `NameError`.
- **Problem 3 (Incomplete Evidence Citations & Correlation Dropping)**: Real OpenAI execution succeeded end-to-end (`status = completed`, `errors = []`, valid causal chain identifying `OrderService.create_order` and `self._failure_controller.is_order_processing_error_enabled()`), but the RCA's `supporting_evidence` only cited runtime evidence and omitted the retrieved code chunk (`chunk-dd04b3223edb3561`), despite making code-level causal claims. Furthermore, `runtime_analysis.request_ids` was dropped when log entries were formatted without explicitly passing `request_id` to the LLM prompt.
- **Root Cause 3**:
  1. The grounding validator in `app/agents/grounding.py` did not enforce mandatory code chunk citation when code-level claims were made, nor mandatory runtime citation when runtime logs were present.
  2. Prompts in `app/agents/prompts.py` did not explicitly mandate citing retrieved code chunk IDs whenever asserting code-level failure sites.
  3. Log formatting in `LangChainInvestigationLLM.analyze_runtime` omitted `e.request_id` in prompt text and relied solely on LLM schema extraction without deterministic fallback preservation.
- **Final Solution**:
  1. **Fixed Undefined Identifier**: Corrected `{chunks_text}` to `{chunks_context}` in `LangChainInvestigationLLM.synthesize_rca`.
  2. **Refined Change Analysis Prompts**: Explicitly instructed `CHANGE_ANALYSIS_SYSTEM_PROMPT` that touching a file does not prove causation and initial/baseline commits must not be treated as regressions or evidence of bugs.
  3. **Strict Lifecycle Status**: Enforced `InvestigationStatus.COMPLETED` only if `rca is not None and validation is not None and validation.valid is True`.
  4. **Shared Deterministic Grounding Validator**: Created and hardened `app/agents/grounding.py`:
     - Requires at least one valid runtime evidence citation if runtime logs exist.
     - Requires at least one valid code chunk citation if code chunks exist and code-level claims are asserted (`failure_location`, `affected_component`, or code symbols in hypothesis/summary).
     - Strictly verifies that every cited ID actually exists in provided evidence context, rejecting fabricated IDs.
     - Uncited or fabricated evidence marks `valid=False`, triggering bounded revision.
  5. **Prompt Hardening**: Updated `RCA_SYNTHESIS_SYSTEM_PROMPT`, `RCA_VALIDATION_SYSTEM_PROMPT`, and `RCA_REVISION_SYSTEM_PROMPT` to mandate citing both runtime evidence and code chunk IDs.
  6. **Correlation & Request ID Preservation**: Added `Request ID: {e.request_id or 'none'}` to runtime prompt lines in `LangChainInvestigationLLM.analyze_runtime` and deterministically preserved all non-empty request IDs from evidence.
  7. **Deterministic Revision Repair**: Equipped `FakeInvestigationLLM.revise_rca` and `LangChainInvestigationLLM.revise_rca` to add missing code chunk and runtime citations when needed during revision.
  8. **Comprehensive Regression Suite**: Added 7 new regression tests (Tests 17–23) in `tests/test_investigation.py` verifying all citation guardrails, revision repairs, and correlation ID preservation.

- **Problem 4 (Runtime Evidence Type/ID Mismatch & Endpoint Enablement Over-Specification)**: Real OpenAI execution successfully reached full RCA generation with runtime, code, Git, and request ID propagation confirmed working. However, the final investigation returned `status = failed` and `validation.valid = false` due to two issues:
  1. The RCA cited a legitimate runtime evidence ID (`37e17189-3d70-48ff-998a-b9a47aeb49e1`) with `type="runtime"`, but the validator reported `"The RCA does not provide a valid runtime evidence reference"` because the semantic validation prompt stripped `ref.type` information (presenting only a string array of IDs) and the deterministic checker strictly expected exact `"runtime"` string matches without normalizing UUIDs or mapping `type="runtime"` to stored `type="runtime_log"` domain representations.
  2. The RCA made an unsupported causal claim stating that the failure mode was enabled via the admin `enable_order_processing_failure` endpoint, when collected incident telemetry contained only the failed `/orders` request without evidence proving the admin endpoint was invoked.
- **Root Cause 4**:
  1. `run_deterministic_grounding_check` lacked flexible type aliasing (`runtime`, `runtime_log`) and whitespace/casing normalization for evidence UUIDs. Furthermore, `LangChainInvestigationLLM.validate_rca` constructed the prompt using raw IDs (`Supporting Evidence IDs Cited: [...]`) rather than structured type-id pairs (`[type=..., id=...]`), leading the LLM auditor to believe no `type="runtime"` citation was provided.
  2. Prompting and validation did not strictly enforce the distinction between "a condition evaluated true" (which can be legitimately inferred from execution path and exception) versus "how that condition became true" (which requires direct supporting telemetry of that specific endpoint invocation or event).
- **Final Solution**:
  1. **Flexible Type Mapping & ID Normalization**: Added `VALID_RUNTIME_TYPES = {"runtime", "runtime_log", "runtime-log"}` and normalized string IDs to guarantee domain `runtime_log` evidence matches `runtime` citations seamlessly.
  2. **Authoritative Citation Reconciliation**: Updated `validate_rca` prompt to show full `[type=..., id=...]` pairs and reconciled deterministic verification so that verified citations cannot be hallucinated as missing by the semantic auditor.
  3. **Causal Precision Prompts**: Hardened `RCA_SYNTHESIS_SYSTEM_PROMPT`, `RCA_VALIDATION_SYSTEM_PROMPT`, and `RCA_REVISION_SYSTEM_PROMPT` to mandate that agents state what condition evaluated true rather than claiming unobserved admin endpoint invocations.
  4. **Unevidenced Endpoint Enablement Validator**: Added deterministic checks rejecting claims that an unobserved admin or enablement endpoint was invoked when telemetry from that endpoint is absent from incident evidence.
  5. **Regression Suite**: Added 8 comprehensive regression tests (Tests 24–31) covering runtime ID acceptance, `runtime_log` mapping, fabricated ID rejection, code chunk ID acceptance, unevidenced endpoint claim rejection, condition evaluation allowance, and bounded revision repair.

- **Problem 5 (Overly Strict Validator Rejecting Legitimate Control-Flow Inference)**: In real OpenAI verification, the workflow produced an appropriately grounded RCA identifying `OrderService.create_order`, `self._failure_controller.is_order_processing_error_enabled() evaluated true`, cited valid runtime and code evidence, and qualified that available evidence did not establish how or when the condition became true. However, validation failed because the validator demanded separate telemetry proving that the boolean condition evaluated true.
- **Root Cause 5**:
  The validator did not recognize grounded control-flow inferences. In the codebase, retrieved source code clearly shows the direct control flow (`if self._failure_controller.is_order_processing_error_enabled(): raise OrderProcessingError(...)`), and runtime traceback proved execution reached the `raise OrderProcessingError` statement inside that branch. Together, `runtime execution reached branch body` + `source code shows branch body executes only when condition is truthy` constitutes a fully grounded control-flow inference. The validator failed to distinguish between:
  - *Allowed*: Grounded control-flow inference (branch condition inferred from executed branch body + source code).
  - *Not allowed*: Historical state-origin claims (how or when the condition became true, e.g. admin endpoint was called, was enabled) without supporting telemetry.
- **Final Solution**:
  1. **Deterministic Branch Extraction & Control-Flow Validation**: Added `_extract_guarded_branches` in `app/agents/grounding.py` utilizing AST parsing with disk fallback and regex support. Verified that:
     - Traceback reaches statement inside branch body -> claim that condition evaluated truthy/falsey is allowed.
     - Traceback does not reach branch body -> truth-value claim is rejected as ungrounded.
     - Fabricated conditions not present in retrieved code fail immediately.
     - Historical state-origin claims ("was enabled", "admin endpoint was called") without telemetry remain strictly rejected.
     - Both runtime evidence and code chunk citations are strictly required to support the branch inference.
  2. **Auditor Prompt Alignment**: Hardened `RCA_VALIDATION_SYSTEM_PROMPT` in `app/agents/prompts.py` to instruct the LLM auditor not to demand separate telemetry for boolean evaluations when execution reached the guarded branch.
  3. **Authoritative Semantic Reconciliation**: Equipped `LangChainInvestigationLLM.validate_rca` in `app/agents/llm.py` to filter out spurious LLM complaints demanding boolean evaluation telemetry when deterministic validation confirms a grounded control-flow inference.
  4. **Regression Suite**: Added 7 new regression tests (Tests 32–38) in `tests/test_investigation.py` covering reached branch allowance, unreached branch rejection, state origin claim rejection, admin endpoint claim rejection, mandatory runtime+code citation pairs, current demo RCA validation, and fabricated condition rejection.

- **Problem 6 (Validation Consistency & Baseline Git Speculation)**:
  1. *Validation Consistency*: In real OpenAI verification, the validator returned `valid = true`, `issues = []`, `unsupported_claims = []`, but `missing_evidence = ["Direct telemetry evidence showing ... evaluated true"]`. This was contradictory: once a control-flow condition inference is accepted as grounded, direct telemetry is satisfied and must not be reported as missing evidence.
  2. *Baseline Git Speculation*: Git change analysis on initial/baseline repository commits contained speculative wording that the initial commit "may have altered the flow" or "may relate to the error". Baseline commits represent initial state, not regressions or alterations to flow, and cannot establish causation.
- **Root Cause 6**:
  1. The semantic/deterministic validation merge did not remove satisfied condition telemetry requirements from `missing_evidence`, and the system lacked an enforced invariant linking `valid = true` to `missing_evidence = []`.
  2. Prompting and change analysis post-processing allowed speculative hedging words ("may have altered", "may relate") on commits identified as baseline commits.
- **Final Solution 6**:
  1. **Strict Validation Invariants**: Enforced in `app/agents/grounding.py` and `app/agents/llm.py` that:
     - Accepted branch condition inference removes spurious telemetry demands from `issues`, `unsupported_claims`, and `missing_evidence`.
     - `valid = true` $\implies$ `missing_evidence = []` (invariant: `valid = true` must NEVER contain unresolved required missing evidence).
     - Genuinely missing required evidence $\implies$ `valid = false` and non-empty `missing_evidence`.
  2. **Baseline Git Non-Speculative Wording**: Updated `CHANGE_ANALYSIS_SYSTEM_PROMPT` (Rule 3) and `analyze_changes` in both fake and real LLM implementations to forbid speculative causal language on baseline commits, ensure they are kept as context without implying regressions or flow alterations, and explicitly state in `potential_relationships` and `inferences` that causation cannot be established from baseline history alone.
  3. **Regression Suite**: Added Tests 39–42 in `tests/test_investigation.py` verifying:
     - Accepted branch inference results in `valid = true` and `missing_evidence = []`.
     - Genuinely missing required evidence results in `valid = false` and non-empty `missing_evidence`.
     - Invariant that `valid = true` never contains unresolved required missing evidence.
     - Baseline Git analysis contains no speculative wording and includes the explicit non-causation disclaimer.

- **Problem 7 (Semantic Validator False Positive Conflating Condition with Enablement & Empty Error Suffix)**:
  1. *Validator False Positive*: In real OpenAI verification, the semantic validator produced a false-positive unsupported claim by conflating "condition evaluated true" with "failure mode was enabled". The validator returned: `unsupported_claims: ["The RCA states that the failure mode 'was enabled' without direct telemetry evidence..."]`, despite the RCA never asserting that the failure mode was enabled (the RCA only stated `self._failure_controller.is_order_processing_error_enabled() evaluated true` and explicitly stated in `uncertainties` that evidence did not establish how or when the failure condition became true).
  2. *Empty Error Message Suffix*: When validation failed with findings in `unsupported_claims` but empty `issues`, `InvestigationService` emitted an incomplete error message `"RCA validation failed: "` because it only joined `validation.issues`.
- **Root Cause 7**:
  1. The validator hallucinated an allegation about text absent from the RCA, and the system lacked claim-presence verification comparing alleged claims against actual text components in the RCA (`failure_location`, `triggering_condition`, `root_cause_hypothesis`, `summary`, supporting evidence, `uncertainties`).
  2. `InvestigationService.investigate` constructed the failure message using only `validation.issues`, ignoring `unsupported_claims` and `missing_evidence`.
- **Final Solution 7**:
  1. **Claim-Presence / Grounding Reconciliation**: Added `get_rca_text_corpus`, `rca_contains_enablement_claim`, and `reconcile_semantic_validation_findings` in `app/agents/grounding.py` and integrated it into `LangChainInvestigationLLM.validate_rca` in `app/agents/llm.py`. Any validator allegation claiming the failure mode "was enabled" or that an enablement endpoint was called is discarded as a false positive if the RCA text itself does not assert enablement claims.
  2. **Preserved Distinctions**: Maintained full support for grounded control-flow inferences (`condition evaluated true` when traceback reached guarded branch + source code shows guard), while strictly retaining rejection when the RCA actually asserts an enablement action occurred without telemetry.
  3. **Robust Error Construction**: Updated `InvestigationService.investigate` in `app/agents/service.py` to build the error message from deduplicated items across `issues`, `unsupported_claims`, and `missing_evidence`, and never emit an empty trailing message like `"RCA validation failed: "`.
  4. **Prompt Hardening**: Clarified in `RCA_VALIDATION_SYSTEM_PROMPT` (`app/agents/prompts.py`) that the validator must evaluate only actual RCA claims and never invent allegations about "was enabled".
  5. **Regression Suite**: Added Tests 43–51 in `tests/test_investigation.py` verifying:
     - RCA with `condition evaluated true` where validator invents `"failure mode was enabled"` -> false-positive finding is discarded (`valid=True`).
     - RCA actually saying `"failure mode was enabled"` without telemetry -> finding remains and validation fails.
     - RCA saying admin endpoint was called without telemetry -> validation fails.
     - Grounded branch-condition inference -> validation passes.
     - Valid RCA -> `missing_evidence=[]`.
     - Valid RCA -> no `"RCA validation failed"` entry in errors.
     - Invalid RCA with only `unsupported_claims` -> error message contains the unsupported claim without empty suffix.
     - Invalid RCA with only `missing_evidence` -> error message is meaningful without empty suffix.
     - Duplicate validation findings across categories are deduplicated.

### Verification
- Executed `pytest -v tests/test_investigation.py`; all 66 tests passed in 15.16s.
- Executed full project test suite `pytest -v`; all 131 tests across Stages 0 through 6 passed in 40.61s with a 100% pass rate and zero regressions.
- Verified zero network calls assertion: test execution does not trigger external network calls.
- Verified valid runtime evidence ID (`37e17189-3d70-48ff-998a-b9a47aeb49e1`) and `runtime_log` mapping are cleanly accepted.
- Verified unevidenced endpoint enablement claims are rejected and cleanly repaired via bounded revision.
- Verified grounded control-flow inferences are accepted while unevidenced state origins and fabricated conditions are rejected.
- Verified validator false-positive enablement allegations are discarded when RCA text contains no enablement claim.
- Verified robust deduplicated error construction on validation failure.
- Verified validation consistency: `valid = true` guarantees `missing_evidence = []`.
- Verified non-speculative baseline Git analysis.

### Known Limitations
- Investigation only; no fix proposal, code patch generation, branch creation, or remediation validation is performed (deferred to later stages).
- In-memory investigation storage; investigation results persist during process runtime but are not stored in an external database.
- Synchronous graph execution; asynchronous task queues (Celery/Redis) are intentionally avoided in Stage 6 to keep the MVP lightweight and testable.

### Real-provider verification
Completed and verified with real OpenAI provider in Stage 6.

### User Approval
Approved

---

## Stage 7 — Incident Memory and Historical RAG

### Objective
Implement deterministic incident memory persistence and historical retrieval (RAG) for SentinelOps without external vector databases or remote embedding APIs. Persist trusted root cause analyses from validated completed investigations, deterministically retrieve prior similar incidents using combined exact categorical scoring and weighted Jaccard lexical overlap, inject historical context strictly as advisory prior knowledge before RCA synthesis, and preserve strict provenance isolation between historical incident records and current incident evidence citations.

### Design Decision
- **Lightweight Deterministic Architecture**: Chose in-memory repository and deterministic scoring over heavy vector databases (ChromaDB/Pinecone) or embedding APIs to keep the platform fast, testable, and dependency-light.
- **Strict Ingestion Gate**: Only investigations satisfying `status == COMPLETED`, `rca != None`, `validation != None`, and `validation.valid == True` are eligible for memory ingestion. Failed, intermediate, or ungrounded investigations are never persisted.
- **Single Trusted Record per Incident**: Memory is keyed by `incident_id`. A subsequent valid investigation on the same incident updates the existing memory in-place (preserving original `created_at`), while subsequent failed or invalid investigations never overwrite an existing trusted memory.
- **Non-Circular Historical Query**: Constructed `HistoricalSearchQuery` strictly before RCA synthesis from current incident metadata, runtime analysis facts (`service`, `endpoint`, `exception_type`, log messages), and code analysis facts (`relevant_symbols`, `relevant_files`). It contains zero dependency on the current incident's RCA.
- **Deterministic Multi-Signal Scoring**:
  - Self-exclusion: candidate matching `current_incident_id` is immediately excluded.
  - Categorical scoring: `service` match (+3.0), `exception_type` match (+4.0), `endpoint` match (+2.0), `failure_location` / symbol match in `relevant_symbols` (+5.0).
  - Lexical scoring: Jaccard token overlap between query text and candidate text multiplied by 3.0.
  - Relevance filtering: threshold `>= 3.0`.
  - Deterministic ranking: descending score with candidate `incident_id` ascending tie-breaker, limited to top 2 results by default.
- **LangGraph Integration**: Inserted `retrieve_historical_context` node between `analyze_changes` and `synthesize_rca`. If memory search fails or is unconfigured, the graph gracefully records a non-fatal warning in `state["errors"]`, sets `historical_context = []`, and synthesis proceeds without crashing.
- **Strict Provenance Isolation**: Historical incidents provide advisory prior knowledge. Current runtime logs, code chunks, and Git facts remain strictly authoritative. `supporting_evidence` in synthesized and revised RCAs is restricted to current incident evidence IDs, code chunk IDs, or Git commit hashes.
- **Minimal Inspection APIs**: Exposed `GET /memory`, `GET /memory/{incident_id}`, and `POST /memory/search`, and included `historical_context` in `InvestigationResponse`.

### Files Added / Changed
- `app/memory/models.py`: Domain dataclasses (`IncidentMemory`, `HistoricalSearchQuery`, `HistoricalIncidentContext`) and Pydantic schemas (`IncidentMemoryResponseSchema`, `HistoricalIncidentContextSchema`, `MemorySearchRequestSchema`, `MemorySearchResponseSchema`).
- `app/memory/repository.py`: Interface `IncidentMemoryRepository` and thread-safe `InMemoryIncidentMemoryRepository`.
- `app/memory/matcher.py`: Deterministic scoring and ranking engine (`IncidentMemoryMatcher`).
- `app/memory/service.py`: Orchestrator `IncidentMemoryService` implementing conditional ingestion and historical search.
- `app/memory/dependencies.py`: Dependency injection providers and repository reset helpers.
- `app/memory/routes.py`: FastAPI endpoints for `GET /memory`, `GET /memory/{incident_id}`, and `POST /memory/search`.
- `app/memory/__init__.py`: Package export interface.
- `app/workflows/investigation_state.py`: Added `historical_context` field to `InvestigationState`.
- `app/workflows/investigation_graph.py`: Added `retrieve_historical_context_node`, wired between `analyze_changes` and `synthesize_rca`, and passed historical context to synthesis and revision.
- `app/agents/models.py`: Added `historical_context` to `Investigation` entity.
- `app/agents/schemas.py`: Added `historical_context` to `InvestigationResponse` schema.
- `app/agents/service.py`: Injected `IncidentMemoryService`, passed it to graph compilation, populated `historical_context`, and auto-ingested eligible completed investigations.
- `app/agents/dependencies.py`: Injected `get_memory_service()` into `get_investigation_service()`.
- `app/agents/llm.py`: Updated `InvestigationLLM` protocol, `FakeInvestigationLLM`, and `LangChainInvestigationLLM` `synthesize_rca` and `revise_rca` signatures and prompt formatting to include advisory historical context.
- `app/agents/prompts.py`: Added historical context and provenance isolation rules to `RCA_SYNTHESIS_SYSTEM_PROMPT`.
- `app/agents/routes.py`: Mapped `historical_context` in `_to_response`.
- `app/api/__init__.py`: Registered `memory_router` in application router.
- `tests/test_memory.py`: 14 comprehensive unit and integration tests covering eligibility, idempotency, scoring, noise filtering, graph execution, failure resilience, and APIs.

### Problems Encountered
- **Problem 1 (Circular Import)**: Importing `HistoricalIncidentContext` into `app/agents/models.py` while `app/memory/service.py` imported `InvestigationStatus` from `app.agents.models` triggered a circular import exception during test discovery.
  - *Solution*: Removed the top-level `InvestigationStatus` import in `app/memory/service.py` and evaluated the normalized lowercase status value against string literal `"completed"`.
- **Problem 2 (Missing Test Client Fixture & Telemetry Setup)**: Initial pytest run in `tests/test_memory.py` failed due to missing `client` fixture and attempted POST to non-existent `/incidents/{id}/evidence` instead of the repository creation pattern used in SentinelOps tests.
  - *Solution*: Added the `client` fixture and an `attach_evidence` helper directly utilizing `get_evidence_repository().create(...)`.

### Verification
- Executed `pytest tests/test_memory.py`: all 14 Stage 7 unit and integration tests passed in 1.03s.
- Executed `pytest tests/test_investigation.py`: all 66 investigation tests passed in 15.25s.
- Executed full project test suite `pytest`: all 145 tests passed in 37.43s with 100% pass rate and zero regressions.
- Verified deterministic noise filtering: candidate sharing only service name is ranked below candidate sharing service + exception + failure location symbol.
- Verified provenance isolation: historical incident IDs never leak into RCA `supporting_evidence`.
- Verified fail-safe execution: graph proceeds and completes even if historical memory search raises an unexpected exception.

### Known Limitations
- Lexical matching operates on token overlap without phonetic stemming or embedding similarity (kept lightweight by design).
- In-memory storage persists during process lifetime and is reset across restarts.

### User Approval
Approved

---

## Stage 8 — Remediation Proposal

### Objective
Implement an AI-assisted, strictly proposal-only remediation system that transforms validated Root Cause Analyses (RCAs) into concrete, actionable, grounded fix proposals. Ensure absolute non-mutation safety (zero writes to source files, zero patch applications, zero git branch creations, commits, or checkouts). Enforce strong file and symbol grounding against the current investigation's retrieved code artifacts, strict evidence provenance isolation, deterministic validation with bounded 1-pass revision, and robust idempotency across re-investigations.

### Design Decisions
- **Proposal-Only Safety Invariant**: The remediation engine acts purely in advisory mode. Production code contains no file writes, patch applications, git checkouts, branch creations, commits, merges, or execution. Automated regression tests verify repository git state invariance before and after proposal generation, while tolerating pre-existing dirty working tree changes.
- **Strict Eligibility Gate**: Proposals can only be requested if:
  - The incident exists.
  - An investigation exists.
  - `investigation.status == InvestigationStatus.COMPLETED`.
  - `investigation.rca != None`.
  - `investigation.validation != None` and `investigation.validation.valid == True`.
  Requests for uninvestigated or non-existent incidents return HTTP 404. Requests for failed or unvalidated investigations return HTTP 409 Conflict with explanatory error details.
- **Strong Target Grounding**:
  - `target_files` must be grounded in the current investigation's `code_results` or `code_analysis.relevant_files`. Real files existing elsewhere in the repo that were not retrieved for the current investigation are strictly rejected.
  - `target_symbols` (when specified) must be grounded in the retrieved code chunks or `code_analysis.relevant_symbols`. Symbols are optional for file-level or configuration changes.
- **Evidence Provenance Isolation**:
  - `evidence_references` must cite only current investigation evidence (runtime log IDs, code chunk IDs, commit hashes).
  - Historical incident IDs from advisory memory context (e.g. `inc-past-123`) are forbidden from masquerading as current grounding evidence.
- **Deterministic Validation & Bounded 1-Pass Revision**:
  - `RemediationValidator` deterministically validates target files, symbols, evidence citations, rationale, risks, and validation steps.
  - If initial generation fails validation, the service performs exactly one revision pass with structured feedback.
  - If validation fails again after revision, the proposal is stored with `status = RemediationStatus.FAILED_VALIDATION`, with full validation details persisted and API-visible.
- **Idempotency & Re-Investigation Lifecycle**:
  - Same `investigation_id` with `regenerate=False`: returns the existing proposal idempotently without invoking the LLM.
  - Same `investigation_id` with `regenerate=True`: regenerates proposal in-place, preserving `remediation_id` and `created_at` while updating `updated_at`.
  - Newer `investigation_id`: automatically generates a fresh proposal with a new `remediation_id` and timestamps, replacing the active proposal for the incident.
- **Provider Architecture**:
  - `RemediationLLM` protocol with `FakeRemediationLLM` for 100% offline, zero-network, deterministic execution.
  - `LangChainRemediationLLM` backed by `ChatOpenAI` with structured JSON outputs and robust fallback parsing.

### Files Added / Changed
- `app/remediation/models.py`: Domain enums (`RemediationStatus`, `ChangeType`), dataclasses (`ProposedChange`, `RemediationValidation`, `RemediationProposal`), exceptions (`RemediationNotFoundError`, `RemediationIneligibleError`), and Pydantic schemas.
- `app/remediation/repository.py`: Interface `RemediationRepository` and thread-safe `InMemoryRemediationRepository`.
- `app/remediation/validator.py`: Deterministic `RemediationValidator` enforcing strong file/symbol grounding, provenance, and structure.
- `app/remediation/prompts.py`: System prompts for remediation proposal generation and bounded revision.
- `app/remediation/llm.py`: `RemediationLLM` protocol, deterministic `FakeRemediationLLM`, and `LangChainRemediationLLM`.
- `app/remediation/service.py`: Orchestrator `RemediationService` handling eligibility checks, generation, bounded revision, and idempotency.
- `app/remediation/dependencies.py`: FastAPI dependency injection providers.
- `app/remediation/routes.py`: FastAPI endpoints for `POST /incidents/{incident_id}/remediation` and `GET /incidents/{incident_id}/remediation`.
- `app/remediation/__init__.py`: Public package exports.
- `app/api/__init__.py`: Registered `remediation_router` in the application router.
- `tests/test_remediation.py`: 17 comprehensive unit and integration tests covering eligibility gates, validation rules, idempotency, revision recovery, zero-mutation safety, and APIs.

### Problems Encountered
- **Problem 1 (FastAPI Dependency Injection in Test Overrides)**: In `test_validation_failure_details_are_persisted_and_api_visible` and `test_bounded_revision_recovers_from_initial_validation_failure`, monkeypatching a locally instantiated `rem_service._llm` did not affect the FastAPI test client, because routes invoke `get_remediation_service` which resolves `get_remediation_llm()` via FastAPI dependency injection.
  - *Solution*: Utilized FastAPI's standard `app.dependency_overrides[get_remediation_llm] = lambda: fake_llm` pattern with clean `finally` teardown, ensuring test client calls route through the overridden mock provider.
- **Problem 2 (Semantic Grounding: Redundant Source-Code Modify on Existing Control Endpoint)**: Real-provider verification with OpenAI exposed that the LLM proposed `target_file: demo_app/api/admin.py`, `target_symbol: disable_order_processing_failure`, `change_type: modify`, with description `"Add a call to disable the order processing error mode before creating an order."`. This was semantically invalid because `disable_order_processing_failure` already disables the failure mode in its retrieved implementation, is an administrative endpoint rather than the order-creation path, and should be represented as an operational/configuration mitigation (`change_type: configuration`) rather than a source-code modification to the control itself.
  - *Root Cause*: Remediation prompts did not instruct the LLM to distinguish operational/configuration mitigations using existing controls from actual source-code modifications to the failing execution path. Furthermore, the validator only checked whether the symbol existed in retrieved code chunks without verifying that the described modification was logically compatible with the symbol's actual retrieved code or whether modifying it to "add disabling behavior" was redundant.
  - *Solution*:
    1. **Prompt Strengthening**: Updated `REMEDIATION_PROPOSAL_SYSTEM_PROMPT` and `REMEDIATION_REVISION_SYSTEM_PROMPT` to explicitly distinguish between operational mitigations (`change_type: "configuration"` for invoking or setting existing controls) and source-code modifications (`change_type: "modify"`, `"add"`, `"remove"` strictly on the faulty execution path). Forbade redundant proposals that add behavior to functions that already implement that exact behavior, and forbade modifying administrative endpoints to inject order-creation logic.
    2. **Deterministic Validator Strengthening**: Added `_check_change_semantic_compatibility` in `RemediationValidator` (`app/remediation/validator.py`). Enforces that source-code modifications (`modify/add/remove`) must not target an existing control symbol to redundantly "add" disabling behavior when the retrieved code already implements that behavior, and must not inject order-creation flow logic into administrative controls. Appropriately represented operational mitigations (`change_type == ChangeType.CONFIGURATION`) using existing controls are cleanly permitted.
    3. **Provider Recovery**: Updated `FakeRemediationLLM` to propose `CONFIGURATION` when encountering existing disable controls, and automatically recover redundant `MODIFY` changes to `CONFIGURATION` on revision.
    4. **Regression Suite**: Added 3 new tests in `tests/test_remediation.py` verifying that redundant `MODIFY` on `disable_order_processing_failure` is rejected with actionable diagnostics, grounded `CONFIGURATION` mitigations on existing controls are accepted, and bounded revision recovers the redundant modification to a valid configuration change.

### Verification
- Executed `pytest tests/test_remediation.py`: all 20 Stage 8 tests passed in 1.13s.
- Executed full project test suite `pytest`: all 165 tests passed in 30.96s with a 100% pass rate and zero regressions across all Stages 0 through 8.
- Verified proposal-only safety: repository `git status --porcelain` is identical before and after proposal generation (zero file writes, zero branch operations, zero commits).
- Verified pre-existing dirty working-tree tolerance: pre-existing unstaged modifications do not invalidate proposal generation.
- Verified strong file and symbol grounding: unretrieved repository files are rejected even if they physically exist on disk.
- Verified provenance isolation: historical incident IDs cannot masquerade as current grounding evidence.
- Verified bounded 1-pass revision: failing initial generation recovers when revised, or is stored as `failed_validation` with full diagnostic details.
- Verified rejection of redundant `MODIFY` proposals on existing disable/reset controls.
- Verified acceptance of grounded `CONFIGURATION` operational mitigations targeting existing controls.

### Known Limitations
- Proposal-only: Does not create git branches, write patches to disk, or execute fixes (deferred to Stage 9 human-in-the-loop approval and execution).
- In-memory proposal storage: Proposals persist during server process runtime.

### User Approval
Approved

---

## Stage 9 — Human Approval and Isolated Git Branch

### Objective
Establish a secure, auditable human-in-the-loop review approval gate and isolated Git branch creation mechanism before any proposed remediation moves toward code mutation. Ensure that:
- Human reviewers can approve, reject, or request revisions on validated remediation proposals.
- Terminal rejection and revision-requested states enforce regeneration semantics, while preserving historical audit trails.
- Git branch management operates on an isolated repository path (`GIT_BRANCH_REPOSITORY_PATH`) rooted strictly at the trusted base branch (`GIT_BASE_BRANCH`), leaving read-only Git intelligence (`GIT_REPOSITORY_PATH`) unaffected.
- Git operations enforce complete working-tree safety, zero code mutation, idempotent branch creation without redundant checkout side effects, and exact duplicate review idempotency.

### Design Decisions
- **Human Review Lifecycle & Invariants**:
  - Reviews support three decisions: `APPROVED`, `REJECTED`, and `REVISION_REQUESTED`.
  - Proposals in `DRAFT` or `FAILED_VALIDATION` status cannot be reviewed.
  - Proposals with stale investigations cannot be reviewed.
  - `REJECTED` is terminal for approval/branching; a rejected proposal cannot later be approved directly. To continue, an operator must regenerate the remediation proposal.
  - `REVISION_REQUESTED` blocks branching and cannot be approved directly without first regenerating the proposal.
  - `APPROVED` proposals lock approval; once branched, approval decisions cannot be altered. Regenerating an `APPROVED` proposal is strictly refused with HTTP 409 Conflict.
- **Review Idempotency Ordering**:
  - In `RemediationReviewService.submit_review`, exact duplicate submissions (`decision`, `clean_reviewer`, `clean_comment`) are verified and returned idempotently *before* applying lifecycle transition restrictions. This ensures that repeating an approval submission does not produce spurious 409 conflicts or create duplicate audit entries.
- **Regeneration Lifecycle Semantics**:
  - `VALIDATED` + `regenerate=true`: In-place proposal refresh, retaining the existing `remediation_id` and `created_at`.
  - `REJECTED` / `REVISION_REQUESTED` + `regenerate=true`: Generates a brand-new proposal with a new `remediation_id`, fresh timestamps, and status reset to `VALIDATED`.
  - Historical proposals are preserved in `RemediationRepository._storage` by `remediation_id`, ensuring past proposals and their review histories remain fully auditable across regenerations.
- **Dual Git Repository Configuration**:
  - Separated `GIT_REPOSITORY_PATH` (used by Stage 5 read-only Git intelligence) from `GIT_BRANCH_REPOSITORY_PATH` (used only by Stage 9 `GitBranchManager`).
  - Added `GIT_BASE_BRANCH` (default `"main"`), defining the trusted base branch required for remediation branching.
- **Git Branch Safety & Branch Manager**:
  - `GitBranchManager` strictly enforces subprocess invocation with `shell=False` and a 10s timeout.
  - Enforces that the repository's active branch equals `GIT_BASE_BRANCH` before allowing branching.
  - Checks tracked working tree cleanliness (`git diff --name-only` and `git diff --cached --name-only`). If uncommitted modifications exist in tracked files, branch creation is refused with HTTP 409 Conflict to protect user work from being stashed, overwritten, or lost.
  - Generates deterministic, sanitized branch names: `sentinel/incident-<incident_id>-fix`, bounded to 100 characters.
  - Pins the branch strictly to the exact HEAD SHA of the configured base branch (`git checkout -b <branch_name> <base_commit>`).
  - Implements branch idempotency without checkout side effects: if a branch already exists for the proposal, the existing `RemediationBranch` entity is returned without re-executing `git checkout`.
  - Performs zero source file modifications, zero patch applications, and zero commits or merges.

### Files Added / Changed
- `app/common/config.py`: Added `git_branch_repository_path` and `git_base_branch` configuration fields.
- `app/remediation/models.py`: Added `ReviewDecision` enum, extended `RemediationStatus` with `APPROVED`, `REJECTED`, `REVISION_REQUESTED`, added dataclasses `RemediationReview` and `RemediationBranch`, exceptions `RemediationReviewError` and `RemediationBranchError`, and Pydantic request/response schemas.
- `app/remediation/repository.py`: Updated `InMemoryRemediationRepository` to retain historical proposals in `_storage` by `remediation_id` and added `list_for_incident(incident_id)`.
- `app/remediation/service.py`: Enforced Stage 9 regeneration rules (refusing approved regeneration with 409; issuing new `remediation_id` for rejected/revision-requested).
- `app/repository/branch_manager.py`: Implemented `GitBranchManager` for branch creation, clean tree checking, and HEAD commit resolution.
- `app/remediation/review_repository.py`: Interface and in-memory repository for chronological review audit trails.
- `app/remediation/branch_repository.py`: Interface and in-memory repository for branch metadata.
- `app/remediation/review_service.py`: Orchestrator `RemediationReviewService` implementing review lifecycle, idempotency ordering, and safe Git branch creation.
- `app/remediation/dependencies.py`: Registered providers `get_review_repository`, `get_branch_repository`, `get_git_branch_manager`, `get_review_service`, and test isolation resetters.
- `app/remediation/routes.py`: Added endpoints `POST /incidents/{incident_id}/remediation/reviews`, `GET /incidents/{incident_id}/remediation/reviews`, `POST /incidents/{incident_id}/remediation/branch`, and `GET /incidents/{incident_id}/remediation/branch`.
- `app/remediation/__init__.py`: Exported Stage 9 public symbols.
- `tests/test_remediation_approval.py`: Comprehensive test suite with 30 tests covering all review lifecycle rules, regeneration preservation, base branch validation, clean working-tree protection, idempotency, and zero-mutation guarantees.
- `docs/PROJECT_JOURNAL.md`: Updated Stage 8 approval and added Stage 9 implementation journal entry.

### Problems Encountered
- **Problem 1 (Review Idempotency Ordering vs. Terminal Lifecycle Checks)**: An engineer resubmitting an identical approval review (same decision, reviewer, and comment) could have triggered the `proposal.status == RemediationStatus.APPROVED` conflict check, resulting in a spurious 409 Conflict.
  - *Solution*: Reordered review validation in `RemediationReviewService.submit_review` so the exact duplicate check runs *before* lifecycle checks (`APPROVED`, `REJECTED`, `REVISION_REQUESTED`). Duplicate submissions return the existing review immediately without creating redundant audit records.
- **Problem 2 (Historical Audit Trail Preservation during Regeneration)**: In Stage 8, `InMemoryRemediationRepository.save` cleaned up prior proposals with `_storage.pop(old_rem_id, None)`. When an operator regenerated a proposal after rejection or revision request, the prior proposal and its review history would become unretrievable.
  - *Solution*: Updated `save` to index the active proposal per incident via `_incident_index[incident_id] = proposal.remediation_id` while retaining all proposals in `_storage[remediation_id]`. Added `list_for_incident` to retrieve complete proposal history ordered chronologically.
- **Problem 3 (Git Repository Configuration Contamination)**: Reusing `GIT_REPOSITORY_PATH` for manual branch verification would have redirected Stage 5 Git intelligence away from `demo_app`, distorting commit context during investigations.
  - *Solution*: Introduced `GIT_BRANCH_REPOSITORY_PATH` specifically for `GitBranchManager`, falling back to `GIT_REPOSITORY_PATH` by default, cleanly separating read-only Git intelligence from branch mutation targets.

### Verification
- Executed `pytest tests/test_remediation_approval.py`: all 30 Stage 9 tests passed in 12.04s.
- Executed full project test suite `pytest`: all 195 tests passed in 1m 16s with 100% success and zero regressions across Stages 0 through 9.
- Verified review decisions: `approved` enables branch creation; `rejected` and `revision_requested` block branch creation with 409 Conflict.
- Verified terminal rejection: `REJECTED` proposal cannot transition to `APPROVED` without regeneration.
- Verified regeneration: `VALIDATED` preserves `remediation_id`; `REJECTED`/`REVISION_REQUESTED` generates fresh `remediation_id`; `APPROVED` regeneration is refused with 409.
- Verified base branch verification: branch creation is refused with 409 if current branch is not `GIT_BASE_BRANCH`.
- Verified working-tree safety: uncommitted tracked changes block branch creation with 409 without discarding, modifying, or stashing user changes.
- Verified zero mutation: branch creation performs zero file edits, zero patch applications, and zero commits.
- Verified branch idempotency: repeated POST /branch returns existing branch record without re-executing `git checkout`.
- **Manual Verification (Live End-to-End Testing)**:
  - Real incident evidence collected from live demo application failure.
  - Completed and valid investigation successfully generated.
  - Validated initial remediation Proposal A.
  - Verified branch creation was blocked before review approval.
  - Submitted Proposal A rejection review.
  - Verified rejected Proposal A could not later be approved (409 Conflict).
  - Verified rejected Proposal A could not create a branch (409 Conflict).
  - Regenerated proposal, producing Proposal B with a brand-new `remediation_id`.
  - Verified historical Proposal A and its review history remained available in audit trail.
  - Verified Proposal B did not inherit Proposal A authorization.
  - Submitted fresh review approving Proposal B.
  - Verified identical repeated approval was idempotent and returned the same `review_id`.
  - Verified review audit history contained exactly two genuine records (rejection for Proposal A, approval for Proposal B).
  - Approved Proposal B successfully created isolated branch `sentinel/incident-<id>-fix`.
  - Verified branch used configured base branch `main`.
  - Verified stored `base_commit` matched `main` HEAD commit SHA.
  - Verified branch creation modified zero files.
  - Verified branch creation created no new Git commit.
  - Repeated branch POST returned the existing branch record idempotently.
  - Repeated branch POST caused no checkout side effect after scratch repository was manually returned to `main`.
  - Confirmed the real SentinelOps repository remained safely on `main`.

### Known Limitations
- Branch creation switches to the isolated branch but does not generate or apply code diffs/patches (deferred to Stage 10 Automated Patch Application and Verification).
- In-memory persistence for reviews and branch records during server process runtime.

### User Approval
Approved

---

## Stage 10 — Sentinel Watcher Foundation

### Objective
Establish the always-on telemetry collection, normalization, in-memory rolling buffering, and durable SQLite local persistence foundation for SentinelOps. Enable continuous monitoring of structured log files (`JsonlFileCollector`), synthetic HTTP service health probes (`HealthCheckCollector`), and canonical push-based external telemetry ingestion (`POST /watcher/events`), while protecting all Stage 0–9 invariants and avoiding premature detection rules or remediation execution.

### Design Decisions
- **Decoupled Telemetry Stream Domain**:
  - Introduced `TelemetryEvent` as a frozen, normalized stream dataclass with an explicit `SignalType` classification (`LOG`, `HEALTH`, `METRIC`, `TRACE`, etc.) separate from `event_type`.
  - Avoided coupling stream telemetry with Stage 3's `Evidence` domain by omitting premature conversion methods.
- **Active Observer Collectors**:
  - Implemented `JsonlFileCollector` as a continuous background tailer with explicit startup EOF semantics (seeks to EOF if the file exists to avoid re-reading historical logs upon startup, and handles truncation/rotation gracefully).
  - Implemented `HealthCheckCollector` using `httpx.AsyncClient` with explicit structured failure typing (`failure_type` preserved in metadata: `connection_refused`, `timeout`, `http_status_failure`, `network_error`).
  - Completely removed host metrics and Docker collector stubs from Stage 10 scope.
- **Canonical HTTP Push Ingestion**:
  - Exposed a single canonical endpoint `POST /watcher/events` accepting single or batch payloads, strictly enforcing explicit non-empty `project_id` and `service` identities (rejecting missing/blank identities with HTTP 422 Unprocessable Entity).
  - Treated HTTP ingestion as a direct route handler rather than a background collector.
- **In-Memory Rolling Bounded Buffer**:
  - Built `RollingTelemetryBuffer` using `collections.deque(maxlen=capacity)` for fast, synchronous, O(1) FIFO eviction upon capacity overflow within the asyncio event loop.
- **SQLite Local Persistence & Retention**:
  - Implemented `SqliteTelemetryStore` using standard library `sqlite3` in WAL mode with indexed lookups.
  - Implemented dual-bounded retention pruning: time-based pruning (`WATCHER_DB_RETENTION_HOURS`, default 24h) and count-based capping (`WATCHER_DB_MAX_EVENTS`, default 10,000 rows).
- **Watcher Lifecycle & Failure Isolation**:
  - Integrated `WatcherService` cleanly into FastAPI's `lifespan` context manager in `app/main.py`.
  - Supervised collector tasks in isolated loops where collector errors never crash the FastAPI backend.

### Files Added / Changed
- `project.md`: Replaced repository-root source-of-truth roadmap with updated architecture defining Stage 10 as Sentinel Watcher Foundation.
- `app/common/config.py`: Added configuration attributes for Watcher (`watcher_enabled`, `watcher_log_path`, `watcher_poll_interval_seconds`, `watcher_buffer_capacity`, `watcher_db_path`, `watcher_db_retention_hours`, `watcher_db_max_events`, `watcher_health_check_interval_seconds`, `watcher_health_check_url`, `watcher_default_project_id`, `watcher_default_service`, `watcher_default_environment`).
- `app/watcher/models.py`: Domain dataclasses and enums (`SignalType`, `CollectorStatus`, `CollectorType`, `WatcherStatus`, `CollectorHealth`, `TelemetryEvent`).
- `app/watcher/schemas.py`: Pydantic request/response schemas for event push, batching, status reporting, and buffered queries.
- `app/watcher/buffer.py`: In-memory `RollingTelemetryBuffer` with bounded deque and reverse-chronological filtered queries.
- `app/watcher/storage.py`: `SqliteTelemetryStore` with table creation, indices, batch saving, and dual-bounded retention pruning.
- `app/watcher/collectors/base.py`: Abstract `TelemetryCollector` protocol.
- `app/watcher/collectors/file_collector.py`: Continuous `JsonlFileCollector` with startup EOF seeking and truncation detection.
- `app/watcher/collectors/health_collector.py`: Synthetic `HealthCheckCollector` with failure categorization.
- `app/watcher/service.py`: `WatcherService` orchestrating collectors, rolling buffer, storage, and queries.
- `app/watcher/dependencies.py`: FastAPI DI providers for buffer, storage, and service singletons with reset hooks.
- `app/watcher/routes.py`: FastAPI endpoints for `POST /watcher/events`, `GET /watcher/status`, and `GET /watcher/events`.
- `app/watcher/__init__.py`: Public package exports.
- `app/api/__init__.py`: Registered `watcher_router` with `api_router`.
- `app/main.py`: Connected `WatcherService` startup and shutdown to application `lifespan`.
- `app/storage/__init__.py`: Exported `SqliteTelemetryStore`.
- `.gitignore`: Scoped runtime SQLite exclusions (`runtime/*.db`, `runtime/*.db-wal`, `runtime/*.db-shm`).
- `tests/test_watcher.py`: 16 comprehensive automated tests covering models, buffer FIFO, SQLite persistence across restart, collectors, and API routes.
- `docs/PROJECT_JOURNAL.md`: Added Stage 10 implementation entry.

### Problems Encountered
- **Problem 1 (Startup Telemetry Duplication)**: If `JsonlFileCollector` read from the start of the log file on boot, previously processed historical logs from prior runs would be re-ingested as duplicate new stream events.
  - *Solution*: Explicitly seek to EOF (`os.path.getsize`) upon startup if the file already exists, setting `_offset` to file size and capturing only newly appended lines.
- **Problem 2 (External Telemetry Identity Leakage)**: Pushing external telemetry without explicit identity could silently attribute events to the local demo application defaults.
  - *Solution*: Enforced mandatory `project_id` and `service` validation in `TelemetryEventCreate` schema with string whitespace stripping, raising HTTP 422 Unprocessable Entity if omitted.

### Attempts
Not applicable; implementation succeeded on first pass according to approved architecture.

### Final Solution
Created the complete `app/watcher` package, hooked lifecycle into `app/main.py`, added configuration parameters, and wrote 16 focused tests in `tests/test_watcher.py`.

### Why It Worked
Strict adherence to decoupled domain boundaries, simple stdlib data structures (`collections.deque`, `sqlite3`), and async task isolation ensured zero side effects on Stages 0–9.

### Verification
- **Automated Verification**:
  - Executed `python -m pytest tests/test_watcher.py -v`: all 16 tests passed in 1.32s with 100% success.
  - Executed full project regression suite `python -m pytest -v`: all 211 tests passed in 30.72s with 100% success (195 baseline tests across Stages 0–9 + 16 new Stage 10 tests).
- **Manual Verification (Completed & Approved)**:
  - SentinelOps Watcher started successfully and remained operational.
  - Queried `GET /watcher/status` and confirmed operational health, active collectors, and bounded buffer diagnostics.
  - Tested external push validation: missing `project_id` on `POST /watcher/events` was predictably rejected with HTTP 422 Unprocessable Entity.
  - Ingested valid external telemetry and confirmed HTTP 202 Accepted.
  - Verified ingested events were retrievable through the Watcher API (`GET /watcher/events`).
  - Verified SQLite persistence across process restart: ingested telemetry survived a complete shutdown and restart of SentinelOps.
  - Verified `JsonlFileCollector` continuously captured newly appended telemetry without duplicating older historical records.
  - Verified `HealthCheckCollector` transitioned between healthy and degraded states.
  - Verified health-check probe failure generated structured `health_check_failed` telemetry preserving the underlying failure classification; the manual verification observed `failure_type="timeout"` with `TimeoutException`.
  - Verified health collector recovered to healthy state after the monitored application resumed.
  - Controlled order-processing failure was enabled successfully on demo application.
  - Confirmed `/orders` returned HTTP 500 while failure mode was active.
  - Confirmed the resulting `OrderProcessingError` was automatically captured by `JsonlFileCollector`.
  - Confirmed the error appeared in SentinelOps as a normalized `TelemetryEvent` in real time without manually invoking `/evidence/collect`.
  - Disabled failure mode and confirmed `/orders` returned HTTP 201, verifying application recovery.

### Known Limitations
- Does not implement detection rules or automatic incident creation (deferred to Stage 11).
- Does not correlate signals into incident evidence bundles (deferred to Stage 12).
- Local collectors configured via environment variables rather than multi-project dynamic registration (deferred to Stage 13).

### User Approval
Approved

---

## Stage 11 — Detection Rules + Automatic Incident Creation

### Objective
Implement deterministic telemetry evaluation on top of the Sentinel Watcher subsystem (Stage 10) to automatically evaluate incoming normalized `TelemetryEvent` streams, detect failure conditions using explicit priority-ordered rules, create incidents via `IncidentService.create_incident()`, attach the triggering telemetry as `Evidence` via `EvidenceRepository`, and enforce duplicate suppression across the running process lifetime using a project-aware composite fingerprint (`project_id | service | environment | rule_id | failure_signature`).

### Design Decisions
- **Deterministic Single-Event Evaluation**: Evaluates incoming `TelemetryEvent` instances against rules in strict priority order with deterministic first-match selection:
  1. Priority 1 (`HealthCheckFailureRule`): Matches `SignalType.HEALTH` with `level="ERROR"` and `event_type="health_check_failed"`. Failure signature: `failure_type|endpoint`. Severity: `HIGH`.
  2. Priority 2 (`AppErrorRule`): Matches `SignalType.LOG` with `level="ERROR"`. Supports all application ERROR logs, with or without unhandled exceptions (Correction 2). Failure signature: `exception_type or event_type|endpoint`. Severity: `HIGH`.
  3. Priority 3 (`Http5xxRule`): Matches `status_code >= 500` with `SignalType.LOG` or `SignalType.CUSTOM` when `level != "ERROR"`, ensuring mutual exclusivity with `AppErrorRule`. Failure signature: `status_code|endpoint`. Severity: `HIGH`.
- **Project-Aware Duplicate Suppression (Correction 1)**: Composite fingerprint strictly encodes `project_id`:
  `fingerprint = f"{event.project_id}|{event.service}|{event.environment}|{match.rule_id}|{match.failure_signature}"`
  Guarantees incidents are never suppressed across different project IDs even if service, environment, and error signatures match.
- **Incident Lifecycle Alignment & Recurrence**:
  - If an active incident for the fingerprint has status `OPEN` or `INVESTIGATING`, subsequent matching events are suppressed (`action=DetectionAction.SUPPRESSED`), incrementing `suppressions_count` without creating duplicate incidents or evidence spam.
  - If an incident has transitioned to `RESOLVED` or `CLOSED`, the fingerprint is cleared and subsequent failure occurrences create a fresh `OPEN` incident.
- **Single Canonical Evaluation Point in WatcherService (Correction 3)**:
  - Evaluation occurs exclusively inside `WatcherService.ingest_event()` after the event is committed to the rolling buffer and SQLite store.
  - `WatcherService.ingest_batch()` delegates each event to `await self.ingest_event(event)`, guaranteeing at-most-once evaluation per event across all ingestion vectors.
- **Evidence Attachment & Typing**:
  - Triggering telemetry is attached as `Evidence` using `EvidenceRepository.create()`.
  - Health events create `EvidenceType.HEALTH_CHECK`; log events create `EvidenceType.RUNTIME_LOG`.
  - `request_id` preserves `event.request_id` or remains `None` without fabricating synthetic identifiers.
  - Contextual metadata (`triggering_event_id`, `project_id`, `rule_id`, and raw metadata) is preserved in `evidence.metadata`.
- **Failure Isolation**:
  - Detection evaluation exceptions are caught and logged inside `WatcherService.ingest_event()`. A failure in detection never crashes Watcher or blocks buffer/storage ingestion.
- **Centralized Configuration & Metrics**:
  - `DETECTION_ENABLED` toggle (`config.detection_enabled`, default `True`) allows disabling detection without affecting telemetry observation.
  - Diagnostic metrics (`evaluations_count`, `matches_count`, `incidents_created_count`, `suppressions_count`, `errors_count`, `active_fingerprints_count`) are exposed in `WatcherStatusResponse`.

### Changes Made
- `app/common/config.py`: Added `detection_enabled: bool` (`DETECTION_ENABLED`, default `True`).
- `app/telemetry/models.py`: Added `HEALTH_CHECK = "health_check"` to `EvidenceType`, made `request_id: Optional[str] = None` on `Evidence`, and updated `fingerprint()` to handle optional request IDs.
- `app/telemetry/schemas.py`: Made `request_id: Optional[str] = None` on `EvidenceResponse`.
- `app/detection/models.py`: Created domain models `DetectionAction` (`INCIDENT_CREATED`, `SUPPRESSED`, `NO_MATCH`), `RuleMatch`, and `DetectionResult`.
- `app/detection/rules.py`: Implemented `DetectionRule` abstract base class and deterministic rules `HealthCheckFailureRule`, `AppErrorRule`, and `Http5xxRule`.
- `app/detection/engine.py`: Implemented `DetectionEngine` with rule evaluation, project-aware suppression, incident creation, evidence attachment, and diagnostic counters.
- `app/detection/dependencies.py`: Created FastAPI dependency injection providers and state reset utilities for `DetectionEngine`.
- `app/detection/__init__.py`: Exported detection domain and engine interfaces.
- `app/watcher/schemas.py`: Added optional `detection` metrics field to `WatcherStatusResponse`.
- `app/watcher/service.py`: Integrated `DetectionEngine` into `WatcherService.__init__`, `ingest_event`, `ingest_batch`, and `get_status`.
- `app/watcher/dependencies.py`: Wired `get_detection_engine()` into `WatcherService` provider and linked `reset_detection_state()` to `reset_watcher_state()`.
- `tests/test_detection.py`: Created 13 comprehensive unit and integration tests covering rule matching, generic ERROR logs, rule precedence, project-aware suppression, recurrence after resolution, evidence typing, canonical batch evaluation, failure isolation, config toggling, and collector-to-incident flows.
- `docs/PROJECT_JOURNAL.md`: Added Stage 11 implementation documentation.

### Verification
- **Automated Verification**:
  - Executed `python -m pytest tests/test_detection.py -v`: all 13 tests passed in 3.55s.
  - Executed full project regression suite `python -m pytest -v`: all 224 tests passed in 35.51s with 100% pass rate (211 baseline tests across Stages 0–10 + 13 new Stage 11 tests; zero regressions).
- **Manual Verification (Completed & Approved)**:
  - Watcher detection diagnostics are operational and reported `errors_count=0`.
  - Normal INFO telemetry is ingested and stored without creating an incident.
  - Generic application `LOG + ERROR` telemetry automatically creates an `OPEN` incident even without `exception_type` or HTTP status.
  - Automatically created incidents are immediately visible through the canonical `/incidents` API.
  - Triggering runtime telemetry is immediately available through the canonical incident Evidence API (`/incidents/{incident_id}/evidence`).
  - Runtime application evidence correctly uses `EvidenceType.RUNTIME_LOG`.
  - Health-check evidence correctly uses `EvidenceType.HEALTH_CHECK`.
  - Real request IDs are preserved when present.
  - Health telemetry without request context correctly preserves `request_id=null`; no synthetic request IDs are fabricated.
  - Evidence metadata preserves `triggering_event_id`, `project_id`, and `rule_id`.
  - Repeated identical failures while an incident is `OPEN` are suppressed.
  - Suppressed telemetry does not create unlimited duplicate evidence.
  - `suppressions_count` increases correctly without increasing `incidents_created_count`.
  - Identical failures from different `project_id` values create separate incidents, proving project-aware suppression.
  - A real demo `OrderProcessingError` flowing through JSONL automatically creates an incident.
  - Health-check failures automatically create health incidents.
  - Repeated health-check failures do not create incident spam.
  - Health collector recovers when the monitored application returns to healthy.
  - After an automatically created incident is transitioned to `RESOLVED`, the same failure fingerprint creates a fresh `OPEN` incident with a new incident ID.

### Known Limitations & Architectural Notes
- Duplicate suppression is process-lifetime only because incidents and suppression state are currently in memory; restarting SentinelOps resets active fingerprints.
- Cross-signal incident correlation remains deferred to Stage 12: a single failed demo request currently produces both an application-error incident from the structured exception log and an HTTP 500 incident from the request-completion telemetry. These are distinct normalized signals whose cross-signal recognition and grouping belong to Stage 12 — Correlation + Rolling Evidence Windows.
- Does not send external notifications (Slack, Webhooks, PagerDuty; deferred to Stage 12).

### User Approval
Approved

---

## Stage 12 — Correlation + Rolling Evidence Windows

### Objective
Implement deterministic telemetry correlation and rolling evidence window capture on top of the Sentinel Watcher and Detection subsystems (Stages 10 & 11) to automatically associate related telemetry events into unified incident evidence bundles, ensuring multiple symptoms of the same failure (e.g., application exception log + HTTP 500 completion log) produce a single incident with comprehensive pre- and post-trigger evidence.

### Design Decisions
- **Canonical Single-Path Orchestration (Clarification 1)**:
  - `WatcherService.ingest_event(event)` appends to the rolling buffer, writes to SQLite, and calls `DetectionEngine.evaluate(event)` exactly once.
  - `DetectionEngine.evaluate(event)` evaluates deterministic detection rules exactly once, obtains `Optional[RuleMatch]`, and calls `CorrelationEngine.observe(event, match)` exactly once, returning the resulting `DetectionResult`.
  - `WatcherService` does not separately invoke `CorrelationEngine`. Batch ingestion delegates each event to `ingest_event()`, ensuring strict at-most-once evaluation across all ingestion vectors.
- **Dual-Key Strong Indexing (Clarification 4)**:
  - When an event contains both `request_id` and `trace_id`, `CorrelationEngine` registers both strong lookup keys:
    - `(project_id, service, environment, request_id)` $\to$ `correlation_id`
    - `(project_id, service, environment, trace_id)` $\to$ `correlation_id`
  - Subsequent events sharing either identifier successfully discover and correlate into the existing active incident.
- **Anchored Fallback Correlation (Clarification 3)**:
  - Fallback correlation (used only when both `request_id` and `trace_id` are absent) compares candidate telemetry occurrence time against the non-sliding `anchor_event_timestamp` of the original triggering event:
    $$\left|\text{event.timestamp} - \text{anchor\_event\_timestamp}\right| \le \text{CORRELATION\_FALLBACK\_WINDOW\_SECONDS (10.0s)}$$
  - Requiring matching `endpoint` and anchoring to the original trigger timestamp prevents "event chaining" where a continuous trickle of minor events could keep an incident open indefinitely.
- **Process-Time Post-Trigger Active Collection Window (Clarification 3)**:
  - When an incident is created, the active correlation collection window expiration is calculated from current process observation time:
    $$\text{expires\_at} = \text{current\_UTC\_process\_time} + \text{CORRELATION\_POST\_WINDOW\_SECONDS (30.0s)}$$
  - Expiration is intentionally decoupled from `event.timestamp` so that backdated or delayed telemetry receives a full 30-second collection window in real process time.
- **Normal/INFO Telemetry Attachment (Clarification 1)**:
  - Normal (non-abnormal) telemetry can never create an incident.
  - A normal event attaches as contextual evidence only when it strongly correlates (matching `request_id` or `trace_id`) to an already-active incident during its post-trigger collection window.
- **Total Evidence Cap & Trigger Preservation (Clarification 2 & Additional Clarification)**:
  - The primary triggering event is always preserved in reserved evidence Slot 1.
  - Total evidence per incident is strictly hard-capped (`CORRELATION_MAX_EVIDENCE_PER_INCIDENT = 20`).
  - Pre-window buffer harvesting is capped at `max_evidence - 1 = 19` slots, preventing pre-trigger logs from crowding out the trigger or post-trigger signals.
  - During pre-window harvesting, `candidate.event_id == triggering_event.event_id` is explicitly excluded to prevent duplicate attachment of the trigger already stored in the buffer.
- **Lifecycle Alignment & Recurrence**:
  - Events correlating to incidents in `OPEN` or `INVESTIGATING` status attach as correlated evidence or suppress duplicates.
  - When an incident is transitioned to `RESOLVED` or `CLOSED`, its active correlation record is invalidated immediately, allowing subsequent failure recurrence to create a fresh `OPEN` incident.
- **Process-Lifetime Boundaries & Restart Semantics**:
  - `SqliteTelemetryStore` persists telemetry durably across restarts.
  - In-memory `IncidentRepository`, `EvidenceRepository`, active correlation indices, and duplicate suppression tables are process-lifetime only and reset upon SentinelOps restart.
- **Scoped Suppression Fingerprints (Discovered & Corrected in Verification)**:
  - When an event is evaluated for duplicate suppression (both for active correlation tracking and fallback duplicate suppression), the suppression fingerprint is scoped by strong transaction identifiers:
    - If `event.request_id` exists: `f"{project_id}|{service}|{environment}|{request_id}|{rule_id}|{failure_signature}"`
    - Else if `event.trace_id` exists: `f"{project_id}|{service}|{environment}|{trace_id}|{rule_id}|{failure_signature}"`
    - Else (legacy no-ID fallback): `f"{project_id}|{service}|{environment}|{rule_id}|{failure_signature}"`
  - Guarantees abnormal events originating from different requests or distributed traces with otherwise identical failure characteristics produce separate incidents, while duplicate emissions within the same request/trace or uninstrumented background probes are suppressed into a single incident.

### Changes Made
- `app/telemetry/models.py`: Added optional `trace_id: Optional[str] = None` to `Evidence` and updated `Evidence.fingerprint()`.
- `app/telemetry/schemas.py`: Added optional `trace_id: Optional[str] = None` to `EvidenceResponse`.
- `app/common/config.py`: Added `correlation_enabled: bool`, `correlation_pre_window_seconds: float` (60.0), `correlation_post_window_seconds: float` (30.0), `correlation_fallback_window_seconds: float` (10.0), and `correlation_max_evidence_per_incident: int` (20).
- `app/watcher/buffer.py`: Added optional query filter arguments to `get_recent()`: `request_id`, `trace_id`, `endpoint`, `start_time`, `end_time`.
- `app/detection/models.py`: Added `CORRELATED = "correlated"` to `DetectionAction` enum.
- `app/correlation/models.py`: Created `ActiveIncidentCorrelation` and `CorrelationType`.
- `app/correlation/engine.py`: Implemented `CorrelationEngine` with dual-key strong indexing, anchored fallback, pre/post window harvesting, total evidence capping, scoped duplicate suppression (`_compute_suppression_fingerprint`), and failure isolation.
- `app/correlation/dependencies.py`: Created dependency injection provider `get_correlation_engine()` and test state resetter `reset_correlation_state()`.
- `app/correlation/__init__.py`: Package exports.
- `app/detection/engine.py`: Refactored to delegate match routing and observation to `CorrelationEngine`.
- `app/detection/dependencies.py`: Injected `get_correlation_engine()` into `DetectionEngine`.
- `app/watcher/dependencies.py`: Added `reset_correlation_state()` to `reset_watcher_state()`.
- `tests/test_correlation.py`: Created 21 comprehensive unit, integration, scoped suppression, and failure isolation tests.
- `docs/PROJECT_JOURNAL.md`: Added Stage 12 documentation and verification closeout.

### Problems Encountered & Resolutions
- **Request-Isolation Defect in Manual Verification**:
  - *Observation*: During manual verification, two abnormal events with identical `(project_id, service, environment, endpoint, event_type, exception_type, rule_id)` but differing `request_id` values (`final-req-A` vs `final-req-B`) collapsed into a single incident instead of producing 2 separate incidents.
  - *Root Cause*: Stage 11 legacy suppression fingerprint calculation omitted `request_id`/`trace_id` when strong correlation lookup failed. After strong correlation rejected the second event due to mismatched `request_id`, execution dropped into fallback suppression against `_active_fingerprints`. Because the suppression fingerprint omitted `request_id`, Event B generated the identical fingerprint to Event A and was erroneously suppressed against Event A's open incident.
  - *Resolution*: Implemented `CorrelationEngine._compute_suppression_fingerprint(event, match)` to scope suppression fingerprints by `request_id`, then `trace_id`, falling back to un-scoped only when neither identifier is present. Updated `_observe_abnormal_telemetry` and `_observe_without_correlation` to use this scoped helper. Added comprehensive test coverage in `tests/test_correlation.py`.

### Verification
- **Automated Verification**:
  - Executed `python -m pytest tests/test_correlation.py -v`: all 21 tests passed in 0.41s.
  - Executed `python -m pytest tests/test_detection.py -v`: all 13 tests passed in 3.46s.
  - Executed full project regression suite `python -m pytest -v`: all 245 tests passed in 38.14s with 100% pass rate (224 baseline tests across Stages 0–11 + 21 new Stage 12 tests; zero regressions).
- **Manual Verification (Completed & Approved)**:
  - A real failed `/orders` request now produces exactly one incident instead of separate AppError and HTTP 500 incidents.
  - The same incident contains:
    - the application exception trigger;
    - pre-trigger INFO request context;
    - the HTTP 500 completion signal as correlated post-trigger evidence.
  - Trigger evidence is stored exactly once.
  - Pre-trigger INFO telemetry sharing the same request_id is captured.
  - Post-trigger INFO telemetry sharing the same request_id attaches to the active incident and does not create a new incident.
  - Unrelated normal INFO telemetry creates no incident.
  - Different request_id values with otherwise identical failure characteristics create separate incidents.
  - Repeated identical failures with the same request_id are suppressed into one incident.
  - Cross-project isolation works even when request_id values are identical.
  - Endpoint/time fallback correlation without request_id/trace_id produces one incident with multiple evidence items.
  - Evidence count is correctly capped at 20 total items.
  - Correlation diagnostics operate correctly.
  - `errors_count=0`.
  - After restarting SentinelOps to load the final suppression fix:
    - different request IDs produced 2 incidents;
    - the same request ID repeated produced 1 incident;
    - `suppressions_count` increased as expected.

### Known Limitations & Architectural Notes
- Active correlation records, suppression fingerprints, in-memory `IncidentRepository`, and `EvidenceRepository` are process-lifetime only; restarting SentinelOps resets active correlation state and active incidents.
- `SqliteTelemetryStore` persists telemetry durably across restarts.
- Project onboarding and repository workspace management remain deferred to Stage 13.
- External notification channels (Slack, Webhooks, PagerDuty) remain deferred to Stage 15.
- Persistent multi-node/distributed correlation remains deferred to a future hardening stage.

### User Approval
Approved

---

## Stage 13 — Project Onboarding + Project Knowledge Base

### Objective
Elevate repository awareness in SentinelOps from a single global configured path to dynamic, multi-tenant project management. Implement first-class project onboarding, workspace identity validation with OS-aware normalization, automatic AST-based route inspection and configuration discovery, persistent metadata storage in SQLite, project-scoped in-memory code indexing and Git change intelligence, lazy restart hydration, atomic reindexing with fatal error preservation, and project-isolated incident investigations with strict zero-leakage fallback guarantees.

### Design Decisions
- **First-Class Project Domain & Persistence**:
  - Implemented `Project` model with lifecycle states: `REGISTERED`, `READY`, and `ERROR`.
  - Persisted project records in SQLite (`SqliteProjectStore`) backed by table `projects`.
  - Stored canonical POSIX workspace path alongside OS-aware normalized path (`normalized_path TEXT NOT NULL UNIQUE`) with `UNIQUE(normalized_path)` constraint to prevent multiple registrations of the same repository workspace.
- **OS-Aware Workspace Normalization**:
  - Derived canonical and normalized workspace paths deterministically:
    `resolved = Path(workspace_path).resolve()`
    `canonical_path = resolved.as_posix()`
    `normalized_path = os.path.normcase(os.path.normpath(str(resolved)))`
  - Validated that target workspace exists, is a directory, and is not a filesystem root drive (e.g. `C:\` or `/`).
  - Handled filesystem case-insensitivity on Windows seamlessly: case-varied registration attempts (e.g. `D:\Repos\Orders` vs `d:\repos\orders`) fold to the identical normalized path and trigger HTTP 409 Conflict.
- **Automated Source Scanner Hardening**:
  - Extended `SourceScanner` with deterministic lexical sorting before applying `max_files` limits.
  - Added configurable `max_files` and `max_file_size` bounds with safe defaults (`project_max_files: 500`, `project_max_file_bytes: 1_000_000`).
  - Expanded directory exclusions: `.venv`, `venv`, `node_modules`, `.git`, `.idea`, `.vscode`, `logs`, `.tox`, `coverage`, `build`, `dist`.
  - Handled external symlinks securely: pruned symlinks that point outside the repository workspace root.
- **AST Route Extraction & Configuration Discovery**:
  - Inspected AST trees across all workspace Python files to detect FastAPI/Flask/Starlette route decorator patterns (`@router.get`, `@app.post`, etc.). Extracted HTTP method, path, relative file path, handler name, and line numbers into `DetectedRoute`.
  - Discovered top-level configuration manifests (`pyproject.toml`, `requirements.txt`, `setup.py`, `setup.cfg`, `Pipfile`, `docker-compose.yml`, `Dockerfile`) into `ConfigFileInfo`.
- **Project-Scoped CodeIndex & Git Intelligence**:
  - In `ProjectKnowledgeService`, maintained separate in-memory `CodeIndex` instances per project ID, isolated behind fine-grained reentrant locks (`threading.RLock`).
  - Discovered Git metadata (`head_sha`, branch) and derived deterministic version tags: `f"v1-{head_sha[:8]}"` for Git projects, `f"v1-{content_hash[:8]}"` for non-Git source projects.
  - Provided project-scoped `GitService` instances pointing exclusively to the project's workspace directory.
- **Lazy Hydration & Version Synchronization**:
  - If SentinelOps restarts (in-memory index dicts cleared), the first query to a `READY` project lazily re-scans and re-indexes the workspace from disk.
  - Automatically computes current `index_version` and updates `last_indexed_at` and `index_version` in SQLite, ensuring persisted database state and active in-memory search match exactly.
- **Non-Destructive Atomic Reindexing & Error Preservation**:
  - Reindexing runs in an atomic staging step. If reindexing succeeds, the new index and snapshot replace the active in-memory structures, and SQLite is updated.
  - If reindexing a `READY` project fails (e.g. directory temporarily moved, unreadable), the previous good in-memory `CodeIndex` and snapshot are preserved and remain searchable; `last_indexed_at` and `index_version` are preserved, status remains `READY`, and the error is recorded in `last_index_error` for diagnostics.
- **Three-Tier Project-Aware Investigation Scoping**:
  - Normalized project identity in investigation workflows via `project_id = getattr(incident, "project_id", None) or "default"`.
  - **Tier 1 (Explicit Onboarded Project)**: If `project_id != "default"` and project is registered in `ProjectKnowledgeService`, retrieval searches exclusively that project's `CodeIndex` and project's `GitService`.
  - **Tier 2 (Legacy Incident Compatibility)**: If `project_id == "default"`, falls back to legacy globally configured `RetrievalService` and `GitService`, ensuring 100% backward compatibility with Stages 4–12 tests.
  - **Tier 3 (Explicit Un-onboarded Project)**: If `project_id != "default"` and project is NOT registered in `ProjectKnowledgeService`, strictly yields empty code results and empty git context, logs a warning, and appends an informative error notice. Crucially, strictly NO legacy fallback is permitted, preventing cross-tenant code leakage.

### Files Added / Changed
- `app/projects/models.py`: Domain models `Project` and `ProjectStatus` (`REGISTERED`, `READY`, `ERROR`).
- `app/projects/schemas.py`: Pydantic schemas `ProjectRegisterRequest` and `ProjectResponse`.
- `app/projects/storage.py`: SQLite persistence store `SqliteProjectStore` with table `projects` and `UNIQUE(normalized_path)`.
- `app/projects/service.py`: Domain service `ProjectService` managing onboarding, workspace validation, and lifecycle.
- `app/projects/dependencies.py`: Dependency injection providers for `SqliteProjectStore` and `ProjectService`.
- `app/projects/routes.py`: FastAPI routes for `POST /projects`, `GET /projects`, `GET /projects/{project_id}`, `POST /projects/{project_id}/reindex`, `GET /projects/{project_id}/knowledge`, `POST /projects/{project_id}/search`.
- `app/projects/__init__.py`: Package exports for project onboarding domain.
- `app/knowledge/models.py`: Domain models `DetectedRoute`, `ConfigFileInfo`, `ProjectKnowledgeSnapshot`.
- `app/knowledge/service.py`: Domain service `ProjectKnowledgeService` providing indexing, lazy hydration, search, endpoint lookup, and scoped Git intelligence.
- `app/knowledge/dependencies.py`: Dependency injection providers for `ProjectKnowledgeService`.
- `app/knowledge/__init__.py`: Package exports for knowledge domain.
- `app/retrieval/scanner.py`: Updated `SourceScanner` with `max_files`, `max_file_size`, external symlink pruning, expanded directory exclusions, and deterministic sorting.
- `app/incidents/models.py`: Added first-class `project_id: str = "default"` to `Incident` model.
- `app/incidents/schemas.py`: Added `project_id: Optional[str] = Field("default", ...)` with validator normalizing `None` to `"default"` in `IncidentCreateRequest`, and `project_id` in `IncidentResponse`.
- `app/incidents/service.py`: Updated incident creation to persist `project_id`.
- `app/correlation/engine.py`: Updated telemetry observation to propagate `event.project_id` to `IncidentCreateRequest`.
- `app/workflows/investigation_graph.py`: Implemented three-tier project scoping in `retrieve_code_node` and `retrieve_git_context_node`.
- `app/agents/service.py`: Updated `InvestigationService` to accept optional `knowledge_service`.
- `app/agents/dependencies.py`: Injected `knowledge_service` into `get_investigation_service`.
- `app/common/config.py`: Added `project_max_files: int = 500` and `project_max_file_bytes: int = 1_000_000`.
- `app/api/__init__.py`: Registered `projects_router` in `api_router`.
- `app/main.py`: Added `close_project_store()` to `lifespan` application shutdown.
- `tests/test_projects.py`: Comprehensive automated test suite with 28 tests covering all Stage 13 requirements and safety isolation.
- `docs/PROJECT_JOURNAL.md`: Documented Stage 13 architecture, decisions, and verification.

### Problems Encountered & Resolutions
- **Circular Import Between Projects and Knowledge Packages**:
  - *Observation*: Initial test collection failed with `ImportError: cannot import name 'ProjectKnowledgeService' from partially initialized module 'app.knowledge.service'`.
  - *Root Cause*: `app.knowledge.service` imported `SqliteProjectStore` from `app.projects.storage` (which triggered `app.projects.__init__`), while `app.projects.service` imported `ProjectKnowledgeService` from `app.knowledge.service`.
  - *Resolution*: Used `from __future__ import annotations` and placed `ProjectKnowledgeService` import under `if TYPE_CHECKING:` in `app/projects/service.py`, cleanly resolving the circular import without runtime penalties.
- **Windows Case-Folding Workspace Normalization**:
  - *Observation*: Needed to guarantee that differing casing of Windows workspace paths (e.g. `C:\Projects\Alpha` vs `c:\projects\alpha`) would be recognized as the exact same repository.
  - *Resolution*: Implemented `normalized_path = os.path.normcase(os.path.normpath(str(resolved)))` and enforced `UNIQUE(normalized_path)` in SQLite schema and `SqliteProjectStore.create_project`. Verified with automated test `test_duplicate_workspace_path_returns_409_including_case_variation`.
- **Fatal Reindex Preservation**:
  - *Observation*: If an indexed project's reindex operation fails due to workspace I/O or filesystem errors, the previously good in-memory `CodeIndex` must remain available for incoming queries.
  - *Resolution*: In `reindex_project()`, performed scanning and parsing into temporary variables before touching `self._project_indexes`. If scanning fails for an already `READY` project, the previous index remains untouched in memory, status remains `READY`, and the error is recorded in `last_index_error`. Verified in `test_fatal_reindex_preserves_previous_good_index`.
- **Git Working-Tree and Configuration Snapshot Index Version Staleness**:
  - *Observation*: During manual verification, adding or modifying uncommitted Python files or discovered configuration files (e.g. `pyproject.toml`) updated served knowledge and `last_indexed_at` after reindex/restart, but `index_version` remained static if Git HEAD had not changed. This violated the invariant that `index_version` reflects the actual snapshot being served.
  - *Resolution*: Updated `_compute_index_version` to hash:
    1. Git HEAD prefix (for Git-backed projects);
    2. Deterministic sorted indexed Python code chunks (relative path, lines, symbol, content);
    3. Deterministic sorted discovered configuration manifests (relative path, file name, size bytes, and content hash).
    Formatted as `f"v1-{head_prefix}-{content_hash}"` (or `f"v1-{content_hash}"` for non-Git projects). This ensures uncommitted working-tree modifications, configuration additions/removals/edits, and HEAD movements all produce distinct, deterministic snapshot versions without using volatile timestamps or mtimes.
- **SQLite Storage Persistence Defect and Test Isolation Failure**:
  - *Observation*: During manual verification, projects registered prior to server restart disappeared from `runtime/sentinelops.db` (`COUNT=0`).
  - *Confirmed Root Cause*: The manual Alpha/Beta project registrations disappeared because Stage 13 automated test suites were using the production/default project database at `runtime/sentinelops.db`. The `tests/test_projects.py` autouse cleanup fixture called `reset_project_state() -> SqliteProjectStore.clear() -> DELETE FROM projects;` against that shared database whenever tests were run. This test isolation failure was the confirmed reason the manually registered projects were deleted. Pre-fix `create_project()` and `update_project()` already explicitly committed successful writes, and normal SentinelOps startup/shutdown did not call `reset_project_state()` and never executed `DELETE FROM projects`.
  - *Durability & Concurrency Hardening*: In addition to isolating test state, multiple durability and concurrency hardening improvements were implemented:
    1. Absolute SQLite path normalization (`self._db_path = str(Path(db_path).resolve())`);
    2. `threading.RLock` synchronization across all store methods;
    3. Explicit transaction rollback on write failures;
    4. Clean project-store lifecycle closure via `close_project_store()` hooked into `app/main.py` `lifespan` application shutdown;
    5. Clean WAL checkpointing (`PRAGMA wal_checkpoint(PASSIVE);`) on shutdown.
  - *Resolution & Verification*: Stage 13 tests were updated to use an isolated temporary project database (`tmp_path / "sentinelops_test.db"`) via `set_custom_project_db_path()`, backed by a dedicated safety regression assertion preventing tests from ever binding to `runtime/sentinelops.db`. Empirical verification confirmed that a production marker inserted into `runtime/sentinelops.db` survived both the Stage 13 focused suite and the full 273-test regression suite untouched. Real server shutdown/restart was manually verified to preserve Alpha/Beta registrations durably.

### Verification
- **Automated Verification**:
  - Executed `python -m pytest tests/test_projects.py -v`: all 28 tests passed in 4.97s.
  - Executed full project regression suite `python -m pytest -v`: all 273 tests passed in 49.75s with 100% pass rate (245 baseline tests across Stages 0–12 + 28 Stage 13 tests; zero regressions; zero warnings).
  - Verified path validation (nonexistent, file, root drive).
  - Verified duplicate project ID and duplicate workspace path (including Windows case-folding).
  - Verified Git vs non-Git project lifecycle and metadata.
  - Verified scanner exclusions, deterministic caps, max file size, and external symlink skipping.
  - Verified SQLite persistence across store re-instantiations and full store destruction/recreation.
  - Verified lazy hydration upon restart syncing in-memory indices and SQLite metadata.
  - Verified multi-project search isolation between Project A and Project B.
  - Verified reindexing updates and fatal reindex preservation of previous good index.
  - Verified working-tree changes without commit update `index_version` on reindex and restart.
  - Verified deterministic versioning on unchanged repositories.
  - Verified Git HEAD changes update `index_version`.
  - Verified adding, modifying, and removing configuration files updates `index_version`.
  - Verified three-tier investigation scoping: onboarded project isolated retrieval, explicit un-onboarded project non-fallback, and legacy incident backward compatibility.
  - Verified incident `project_id` propagation from Watcher telemetry and `None` -> `"default"` normalization.
  - Verified legacy `/repository/status` and `/repository/search` compatibility.
  - Verified durable registration and updates across independent connection lifecycles.
  - Verified API and service recreation across process shutdown simulation.
  - Verified test DB isolation ensures automated tests never bind to or mutate live `runtime/sentinelops.db`.

- **Manual Verification**:
  - Project onboarding and durable SQLite persistence verified across real server restart.
  - Git-backed and non-Git projects verified.
  - Project-scoped CodeIndex isolation verified with Alpha/Beta repositories.
  - Windows case-insensitive duplicate workspace detection verified.
  - Lazy hydration after restart verified.
  - Deterministic composite `index_version` verified:
    - Git HEAD identity;
    - indexed source content;
    - discovered config manifests.
  - Uncommitted Git working-tree changes verified to advance the knowledge hash while keeping HEAD prefix unchanged.
  - Deleted source disappears after successful reindex.
  - First-class `Incident.project_id` verified.
  - Onboarded Alpha investigation uses only Alpha source/Git context.
  - Explicit unknown project returns empty code/Git context with no legacy fallback.
  - Failed READY reindex verified:
    - HTTP 422;
    - READY preserved;
    - prior `index_version` preserved;
    - prior `last_indexed_at` preserved;
    - `last_index_error` populated;
    - previous in-memory CodeIndex remains searchable;
    - successful recovery clears `last_index_error`.
  - Test DB isolation verified so Stage 13 tests no longer mutate `runtime/sentinelops.db`.

### Known Limitations & Architectural Notes
- Workspace file watching / automated real-time filesystem change triggers remain deferred to future stages (reindexing is currently triggered via API endpoint `POST /projects/{project_id}/reindex`).
- Multi-node distributed caching of in-memory code indices remains deferred to future hardening stages.
- Investigation reporting and automated remediation continue to leverage project-scoped context provided by `ProjectKnowledgeService`.

### User Approval
Approved

---

## Stage 14 — Deployment / Telemetry Connectors

### Objective
Connect external deployment lifecycles and runtime telemetry platforms (CI/CD pipelines, synthetic health observers, metrics platforms, runtime monitoring systems) into SentinelOps' proactive incident detection, investigation, and operational memory pipeline. Ensure strict project scoping, credential redaction, foreign key data integrity, Option B at-least-once deduplication semantics, and target vs operational health classification.

### Design Decisions
- **Connector Type Scope**: Formally restricted to two core implementations: `http_poller` and `webhook`. Provider-specific adapters (GitHub, GitLab, Datadog, ArgoCD, Kubernetes) are deferred to future expansion. A generic normalization layer converts external payloads into the canonical Stage 10 `TelemetryEvent` contract.
- **Canonical Telemetry Reuse**: Reused the exact frozen `TelemetryEvent` dataclass from `app/watcher/models.py`. Did not introduce replacement contracts. All events feed directly into `WatcherService.ingest_event()`.
- **Shared SQLite Persistence & Connection Pragma**: Connectors share the exact metadata SQLite database as projects (`runtime/sentinelops.db` in production; redirected to `tmp_path / "sentinelops_test.db"` in automated tests). Both `SqliteProjectStore` and `SqliteConnectorStore` enforce `PRAGMA foreign_keys = ON;` on every SQLite connection.
- **Foreign Key ON DELETE RESTRICT & Domain Decoupling**: Database schema enforces `FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE RESTRICT`. Deleting a project with child connectors raises `sqlite3.IntegrityError`, which `SqliteProjectStore` catches and translates to `ProjectHasActiveConnectorsError`. `ProjectService` re-raises this domain error without importing `ConnectorStore`, and FastAPI translates it to `HTTP 409 Conflict`.
- **Secret Redaction and Masking Boundary**: Plaintext local SQLite persistence with strict API/log/diagnostic redaction (encryption at rest deferred to Stage 20). API responses mask credentials (`sk-****-1234` or `[REDACTED]`). Updates with masked values preserve stored credentials.
- **Option B Deduplication Guarantee**: Per-connector async lock serializes delivery. Checks `connector_dedup_log`. Calls `WatcherService.ingest_event()` first. Only after successful return commits `(connector_id, external_event_id)` into SQLite. Guarantees at-least-once delivery; normal retries with stable external IDs are suppressed; process crash before dedup commit may re-process on retry (exactly-once is explicitly not guaranteed).
- **Explicit Ingestion Endpoint**: Restricted to single route `POST /connectors/{connector_id}/ingest`, eliminating ambiguous global header matching.
- **Failure Classification**: Distinguishes Target Health Failures (HTTP 4xx/5xx, timeouts, connection refused, DNS errors — emits HEALTH failure telemetry, marks target unhealthy, does not back off poller loop) from Operational Connector Errors (internal code defect, local SQLite write lock — degrades connector health, applies exponential backoff, does not emit fake target telemetry).

### Files Added / Changed
- `app/connectors/__init__.py`: Package initialization.
- `app/connectors/models.py`: Data models and schemas (`Connector`, `ConnectorConfig`, `ConnectorHealth`, `ConnectorType`, `WebhookIngestRequest`, `ConnectorResponse`).
- `app/connectors/store.py`: `SqliteConnectorStore` with connection-scoped `PRAGMA foreign_keys = ON;`, tables `connectors`, `connector_dedup_log`, `connector_health`, and cascade/restriction support.
- `app/connectors/auth.py`: HMAC signature verification (`X-Hub-Signature-256`, etc.) and Bearer token validation.
- `app/connectors/redaction.py`: Recursive secret scrubbing and API response masking engine.
- `app/connectors/normalizer.py`: Normalizer mapping external webhook and poller bodies into canonical Stage 10 `TelemetryEvent`.
- `app/connectors/poller.py`: `ConnectorPollerRuntime` background async worker managing polling intervals and backoff.
- `app/connectors/service.py`: `ConnectorService` coordinating business logic, auth, Option B deduplication, and Watcher delegation.
- `app/connectors/dependencies.py`: Dependency injection providers with test DB redirection (`set_custom_connector_db_path`).
- `app/connectors/routes.py`: FastAPI router for `/connectors` CRUD, `/ingest`, `/collect`, and `/test`.
- `app/api/__init__.py`: Registered `connectors_router` in aggregated API router.
- `app/main.py`: Hooked `ConnectorPollerRuntime` startup/shutdown and `close_connector_store()` into FastAPI `lifespan`.
- `app/projects/storage.py`: Enabled `PRAGMA foreign_keys = ON;` in `_init_db()`, added `ProjectHasActiveConnectorsError`, caught `IntegrityError` in `delete_project()`.
- `app/projects/service.py`: Imported `ProjectHasActiveConnectorsError` and allowed propagation on project delete.
- `app/projects/routes.py`: Added `DELETE /projects/{project_id}` endpoint with HTTP 409 Conflict handling.
- `tests/test_connectors_store.py`: Unit tests for store CRUD, foreign keys, cascades, and dedup.
- `tests/test_connectors_service.py`: Tests for Option B deduplication, redaction, auth, and secret preservation.
- `tests/test_connectors_poller.py`: Tests for target vs operational failure classification, recovery, and restart task lifecycle.
- `tests/test_connectors_api.py`: Full API acceptance suite with isolated `tmp_path` test database.

### Verification
- **Automated Verification**:
  - Executed focused connector test suite `python -m pytest (Get-Item tests/test_connectors*.py) -v`: all 33 tests passed in 6.73s (0 warnings).
  - Executed full project regression suite `python -m pytest -v`: all 306 tests passed in 50.99s with 100% pass rate (273 baseline tests across Stages 0–13 + 33 Stage 14 tests; zero regressions; zero warnings).
  - Verified connector CRUD lifecycle, 404 for unknown connector, 404 for unknown project.
  - Verified foreign key ON DELETE RESTRICT and project deletion 409 Conflict while connectors exist.
  - Verified Option B deduplication: stable external ID suppression, no-ID at-least-once delivery, Watcher failure non-persistence.
  - Verified recursive secret redaction and masked secret update preservation.
  - Verified poller target error emits HEALTH telemetry without operational backoff; operational error degrades connector health without fake target telemetry.
  - Verified poller background task enable/disable lifecycle across simulated restart.
  - Verified test DB isolation ensures automated tests never mutate `runtime/sentinelops.db`.

- **Runtime Blockers Discovered & Hardened During Real Manual Verification**:
  - Lifespan dependency bug: direct lifespan call received FastAPI `Depends` object instead of concrete connector store/runtime; fixed by resolving concrete instance directly.
  - Async lifecycle bug: synchronous connector API route executed in worker thread and called `asyncio.create_task`, causing `RuntimeError: no running event loop`.
  - Zombie connector persistence: three zombie Stage 14 manual connector rows were found because persistence occurred before runtime activation failure.
  - Connector runtime lifecycle moved to async request/service paths (`async def` routes and async service methods on the main event loop).
  - Create/update compensation rollback added: persists only on successful runtime activation; rolls back store mutation if runtime task startup fails.
  - Database cleanup: zombie Stage 14 manual connector artifacts removed from `runtime/sentinelops.db` without touching unrelated project data.

- **Completed Manual Verification**:
  - Real Uvicorn startup clean with shared runtime;
  - Webhook and HTTP poller creation 201;
  - Secret redaction verified;
  - Bad auth 401 without connector degradation;
  - Valid webhook ingest 200;
  - Connector-bound `project_id` overrides spoofed payload project ID;
  - Stage 14 Beta incident created and cross-project contamination = 0;
  - Stable external ID duplicate suppressed with incident count unchanged;
  - Events without external IDs are processed independently;
  - Disabled webhook ingest 409;
  - Webhook collect guard 400;
  - HTTP poller webhook-ingest guard 400;
  - Unreachable HTTP target classified as target unhealthy with 0 operational errors;
  - Disabling poller stops `last_poll_at`;
  - Re-enabling resumes polling;
  - SQLite persistence verified;
  - Project deletion with dependent connector returns 409;
  - Restart restores active HTTP poller while webhook remains passive;
  - `/test` diagnostic succeeds without incrementing operational error counters;
  - Deleting connector allows project deletion; subsequent project GET returns 404.

### User Approval
Pending Verification
