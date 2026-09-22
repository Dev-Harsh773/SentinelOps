# SentinelOps

AI-assisted software reliability and incident-response platform.

## Current Stage

**Stage 4 — Repository / Source-Code Indexing**

### Current Implementation Status & Scope Note
> **Important Scope Note:**  
> This repository is currently at **Stage 4 only**.  
> In this stage, SentinelOps provides deterministic, lexical repository scanning, AST-based semantic chunking, in-memory indexing, and source-code retrieval for the demo application:
> 1. `SourceScanner` scans the configured repository path (`SOURCE_REPOSITORY_PATH=demo_app`), discovering Python (`.py`) source files while strictly ignoring non-target directories (`tests/`, `runtime/`, `.git/`, `__pycache__/`, virtual environments).
> 2. `PythonAstParser` extracts non-overlapping semantic `CodeChunk` objects:
>    - Functions preserve decorators (e.g. `@router.post(...)`) with line ranges starting at the decorator.
>    - Classes are extracted without duplicating method bodies; methods are individually chunked with `ClassName.method_name`.
>    - Top-level statements, imports, constants, and module docstrings are extracted as module chunks without duplicating function/class bodies.
>    - Stable deterministic SHA-256 chunk IDs (`chunk-<hash>`) derived from `(file_path, symbol_name, symbol_type, start_line, end_line)`.
> 3. `CodeIndex` maintains an in-memory index with atomic rebuilds and lexical scoring:
>    - Scoring hierarchy: Exact symbol match > symbol tokens > file path tokens > content tokens.
>    - Deterministic tie-breaking: `(-score, file_path, start_line)`.
>    - Relevance threshold: Nonsense queries return `results: []`.
> 
> **Explicit Scope Boundary:**  
> No embeddings, vector databases (Chroma/FAISS/Qdrant), LLMs, LangChain/LangGraph, or Git commit history analysis are used.  
> Retrieved code is NOT automatically attached to incidents or analyzed for root-cause yet.

---

## Prerequisites

- Python 3.10+ (tested on Python 3.12)
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

---

## Installation

Install the required minimal dependencies:

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

## Stage 4 Source-Code Indexing & Retrieval Workflow

### 1. Check Index Status (Before Indexing)
In Terminal:
```powershell
curl.exe http://127.0.0.1:8000/repository/status
```
**Expected Response:**
```json
{
  "indexed": false,
  "files_indexed": 0,
  "chunks": 0,
  "repository": null,
  "indexed_at": null
}
```

Attempting to search before indexing returns HTTP 409 Conflict:
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/repository/search -H "Content-Type: application/json" -d "{\"query\":\"order processing\"}"
```

### 2. Trigger Repository Indexing
```powershell
curl.exe -X POST http://127.0.0.1:8000/repository/index
```
**Expected Response (200 OK):**
```json
{
  "repository": "demo_app",
  "files_discovered": 18,
  "files_indexed": 18,
  "files_skipped": 0,
  "chunks_created": 38,
  "indexed_at": "2026-09-23T..."
}
```

### 3. Check Index Status (After Indexing)
```powershell
curl.exe http://127.0.0.1:8000/repository/status
```
**Expected Response:**
```json
{
  "indexed": true,
  "files_indexed": 18,
  "chunks": 38,
  "repository": "demo_app",
  "indexed_at": "2026-09-23T..."
}
```

### 4. Search by Failure Concept
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/repository/search -H "Content-Type: application/json" -d "{\"query\":\"order processing failure\",\"limit\":5}"
```
Returns relevant chunks from failure toggles, controllers, and order services with normalized POSIX paths (`demo_app/...`).

### 5. Search by Exact Symbol Name
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/repository/search -H "Content-Type: application/json" -d "{\"query\":\"OrderService.create_order\",\"limit\":3}"
```
Returns the exact method chunk at the top with a high boost score.

### 6. Verify Relevance Threshold on Unrelated Queries
```powershell
curl.exe --% -X POST http://127.0.0.1:8000/repository/search -H "Content-Type: application/json" -d "{\"query\":\"quantum banana spaceship\"}"
```
**Expected Response:**
```json
{
  "query": "quantum banana spaceship",
  "total": 0,
  "results": []
}
```

---

## Running Automated Tests

Run the complete test suite across SentinelOps, Demo App, Telemetry, and Retrieval:

```powershell
pytest -v
```
All 47 tests pass with 100% success rate and zero regressions.
