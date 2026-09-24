# SentinelOps

AI-assisted software reliability and incident-response platform.

## Current Stage

**Stage 6 — First LangGraph / AI Investigation Workflow**

### Current Implementation Status & Scope Note
> **Important Scope Note:**  
> This repository is currently at **Stage 6 only**.  
> In this stage, SentinelOps combines deterministic incident management (Stage 1), runtime telemetry evidence (Stage 3), source-code AST retrieval (Stage 4), and Git change intelligence (Stage 5) through a multi-node LangGraph orchestration workflow:
> 1. `load_context` / `analyze_runtime`: Extracts observable runtime symptoms, HTTP endpoints, exception types, correlation IDs, and timeline from attached incident evidence logs without inventing missing data.
> 2. `retrieve_code`: Constructs a focused query (`exception_type` + event concept) and performs deterministic lexical retrieval via `RetrievalService`.
> 3. `analyze_code`: Evaluates retrieved source-code chunks against the runtime failure, pinpointing candidate execution paths and methods.
> 4. `retrieve_git_context`: Performs deterministic, bounded Git inspection (`GitService`) for the top relevant code files.
> 5. `analyze_changes`: Distinguishes factual code changes from causal inferences, strictly avoiding the assumption that temporal proximity proves causation.
> 6. `synthesize_rca`: Synthesizes an evidence-grounded Root Cause Analysis (RCA) citing stable evidence references (runtime evidence UUIDs, deterministic code chunk IDs, commit hashes).
> 7. `validate_rca`: Adversarially audits the RCA for hallucinations, fabricated technologies (e.g. unprovided databases/caches), ungrounded claims, or uncited references.
> 8. `revise_rca`: Automatically triggers a bounded revision loop (maximum 1 revision) if validation fails, restricting revisions strictly to already-retrieved evidence.
> 
> **Explicit Scope Boundary:**  
> - **Investigation Only**: Stage 6 produces a probable root cause hypothesis and structured investigation report.
> - **Strictly Prohibited in Stage 6**: SentinelOps does **NOT** modify source code, generate code patches, create Git branches, commit, push, merge, deploy, or automatically resolve incidents.
> - **Zero Direct Tool Access for LLM**: The LLM does not execute shell commands, read arbitrary files, or query Git directly. All context is fetched by deterministic services and passed into LLM nodes.
> - **100% Offline Testing**: Automated tests run deterministically using `FakeInvestigationLLM` requiring zero external API keys, zero network connectivity, and zero cost.

---

## Prerequisites

- Python 3.10+ (tested on Python 3.12)
- Git (command-line client installed and on system PATH)
- pip

---

## Environment Setup

1. (Optional) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

2. Copy the example configuration file:
   ```bash
   cp .env.example .env
   ```
   *(Or copy on Windows PowerShell: `Copy-Item .env.example .env`)*

### LLM Configuration (.env)
```ini
# LLM Provider: 'mock' (default, offline deterministic) or 'openai'
LLM_PROVIDER=mock
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=
```

---

## Installation

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Running the Applications

### 1. Start SentinelOps (Port 8000)
In Terminal 1:
```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- Health Check: `http://127.0.0.1:8000/health`
- Swagger UI: `http://127.0.0.1:8000/docs`

### 2. Start Demo Application (Port 8001)
In Terminal 2:
```powershell
uvicorn demo_app.main:app --reload --host 127.0.0.1 --port 8001
```
- Health Check: `http://127.0.0.1:8001/health`
- Swagger UI: `http://127.0.0.1:8001/docs`

---

## Stage 6 End-to-End Investigation Demo Workflow

Follow these steps to experience the complete investigation flow:

### Step 1: Index Demo Application Code
```powershell
curl.exe -X POST http://127.0.0.1:8000/repository/index
```

### Step 2: Create an Incident in SentinelOps
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/incidents -H "Content-Type: application/json" -d "{\"title\":\"Order Checkout Failure\",\"summary\":\"Multiple 500 errors during checkout\",\"severity\":\"high\",\"service\":\"order-service\",\"environment\":\"production\"}"
```
*Note the returned `"id"` (e.g., `INCIDENT_ID`).*

### Step 3: Trigger Controlled Failure in Demo App
```powershell
# Enable the failure mode
curl.exe -X POST http://127.0.0.1:8001/admin/failures/order-processing/enable

# Place an order to generate runtime failure log
curl.exe --% -X POST http://127.0.0.1:8001/orders -H "Content-Type: application/json" -d "{\"product_id\":\"p1\",\"quantity\":1}"
```
*Note the `"request_id"` in the 500 error response headers or body.*

### Step 4: Collect Runtime Evidence into Incident
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/incidents/INCIDENT_ID/evidence/collect -H "Content-Type: application/json" -d "{\"request_id\":\"REQUEST_ID\"}"
```

### Step 5: Run LangGraph Investigation
```powershell
curl.exe -X POST http://127.0.0.1:8000/incidents/INCIDENT_ID/investigate
```

### Step 6: Inspect Structured Investigation Result
```powershell
curl.exe http://127.0.0.1:8000/incidents/INCIDENT_ID/investigation
```
**Expected Structured Output:**
```json
{
  "investigation_id": "...",
  "incident_id": "INCIDENT_ID",
  "status": "completed",
  "runtime_analysis": {
    "service": "order-service",
    "endpoint": "/orders",
    "exception_type": "OrderProcessingError",
    "observed_failures": ["OrderProcessingError occurred in order-service"]
  },
  "code_query": "OrderProcessingError order processing failed",
  "code_results": [
    {
      "id": "chunk-dd04b3223edb3561",
      "file_path": "demo_app/services/order_service.py",
      "symbol_name": "OrderService.create_order",
      "symbol_type": "method"
    }
  ],
  "code_analysis": {
    "relevant_symbols": ["OrderService.create_order"],
    "relevant_files": ["demo_app/services/order_service.py"]
  },
  "git_context": [
    {
      "file_path": "demo_app/services/order_service.py",
      "commits": [...]
    }
  ],
  "rca": {
    "root_cause_hypothesis": "Failure in OrderService.create_order due to OrderProcessingError",
    "affected_component": "OrderService.create_order",
    "confidence": 0.85,
    "supporting_evidence": [
      { "type": "runtime", "id": "..." },
      { "type": "code", "id": "chunk-dd04b3223edb3561" },
      { "type": "git_commit", "id": "..." }
    ],
    "uncertainties": []
  },
  "validation": {
    "valid": true,
    "issues": [],
    "unsupported_claims": []
  }
}
```

---

## Running Automated Tests

Run the complete test suite across all modules (Stages 0–6):

```powershell
pytest -v
```
All 77 tests pass with a 100% success rate, 0 regressions, and 0 external network calls.
