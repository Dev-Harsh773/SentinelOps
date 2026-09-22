# SentinelOps

AI-assisted software reliability and incident-response platform.

## Current Stage

**Stage 5 — Git Change Intelligence**

### Current Implementation Status & Scope Note
> **Important Scope Note:**  
> This repository is currently at **Stage 5 only**.  
> In this stage, SentinelOps provides deterministic, read-only local Git repository change intelligence:
> 1. `GitClient` interacts with the local Git repository via Python's standard `subprocess` with `shell=False` and strict read-only commands (`rev-parse`, `log`, `show`, `diff-tree`).
> 2. `GitService` coordinates repository validation, commit hash format enforcement (`^[0-9a-fA-F]{7,40}$`), path traversal protection, diff truncation (bounded at 50,000 characters), and history queries.
> 3. Logical repository identity is exposed as `"sentinelops"`, never leaking local machine-specific physical filesystem paths.
> 4. Endpoints exposed:
>    - `GET /git/commits?limit=10` — List recent commits (newest first).
>    - `GET /git/commits/{commit_hash}` — Detailed commit metadata and changed files with additions/deletions.
>    - `GET /git/commits/{commit_hash}/diff` — Unified textual diff for the commit or a specific file, with bounded truncation.
>    - `GET /git/files/history?path=...&limit=10` — Commit history for a specific file (including deleted files).
> 
> **Explicit Scope Boundary:**  
> - **Local Git Only**: Operates strictly on local `.git` repository data. No GitHub APIs, GitLab APIs, tokens, or external network requests are used.
> - **Strict Read-Only Safety**: SentinelOps never mutates Git history (no commit, push, checkout, branch, merge, reset, clean, or stash).
> - **Factual Change Intelligence Only**: Stage 5 answers *what changed* and *when*. It does **NOT** declare causality or claim that a commit caused an incident. AI reasoning and automated root-cause analysis remain deferred to Stage 6.

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

## Stage 5 Git Change Intelligence Workflow

### 1. List Recent Commits
In Terminal:
```powershell
curl.exe "http://127.0.0.1:8000/git/commits?limit=5"
```
**Expected Response:**
```json
{
  "repository": "sentinelops",
  "commits": [
    {
      "commit_hash": "ea2797a806eacc058a886f9f08cd885e3d91c668",
      "short_hash": "ea2797a",
      "author_name": "Dev-Harsh773",
      "author_email": "krishringi123@gmail.com",
      "authored_at": "2026-09-23T01:15:07+05:30",
      "committed_at": "2026-09-23T01:15:07+05:30",
      "message": "Initial SentinelOps implementation through Stage 4"
    }
  ]
}
```

### 2. Inspect Commit Details
Replace `<commit_hash>` with your commit hash (e.g. `ea2797a` or full 40-char hash):
```powershell
curl.exe "http://127.0.0.1:8000/git/commits/ea2797a"
```
**Expected Response (200 OK):**
```json
{
  "commit": {
    "commit_hash": "ea2797a806eacc058a886f9f08cd885e3d91c668",
    "short_hash": "ea2797a",
    "author_name": "Dev-Harsh773",
    "author_email": "krishringi123@gmail.com",
    "authored_at": "2026-09-23T01:15:07+05:30",
    "committed_at": "2026-09-23T01:15:07+05:30",
    "message": "Initial SentinelOps implementation through Stage 4"
  },
  "changed_files": [
    {
      "file_path": "demo_app/services/order_service.py",
      "change_type": "added",
      "old_path": null,
      "additions": 67,
      "deletions": 0
    }
  ]
}
```

### 3. Inspect Commit Unified Diff
```powershell
curl.exe "http://127.0.0.1:8000/git/commits/ea2797a/diff"
```
Or filter the diff to a specific repository-relative file path:
```powershell
curl.exe "http://127.0.0.1:8000/git/commits/ea2797a/diff?path=demo_app/services/order_service.py"
```

### 4. Inspect Single-File Commit History
```powershell
curl.exe "http://127.0.0.1:8000/git/files/history?path=demo_app/services/order_service.py&limit=10"
```
Returns all commits that modified that file (including root commits and deleted files), newest first.

---

## Running Automated Tests

Run the complete test suite across SentinelOps, Demo App, Telemetry, Retrieval, and Git Repository:

```powershell
pytest -v
```
All 65 tests pass with a 100% success rate and zero regressions.
