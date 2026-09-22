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
Pending
