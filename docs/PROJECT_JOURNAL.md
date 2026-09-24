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
Pending (manual verification with OpenAI provider)

### User Approval
Pending


