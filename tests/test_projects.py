"""Stage 13 Automated Tests: Project Onboarding and Project Knowledge Base.

Validates:
1. Workspace path validation (existence, file vs directory, root drive protection).
2. OS-aware normalization and duplicate checks (project_id, canonical path, Windows case-folding).
3. Project onboarding lifecycle (Git projects vs non-Git source-only projects, status READY).
4. Scanner enhancements (exclusions, deterministic max_files cap, max_file_size limit, external symlink safety).
5. Persistence across restarts and lazy hydration.
6. Reindexing operations (updates, additions, deletions, and fatal error preservation with last_index_error).
7. Multi-project search isolation (Project A vs Project B).
8. Investigation project-aware isolation, un-onboarded explicit project non-fallback, and legacy incident compatibility.
9. Incident project_id propagation and normalization (None -> "default").
10. Legacy repository endpoints backwards compatibility without any onboarded projects.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
from typing import Generator
import uuid
import pytest
from fastapi.testclient import TestClient

from app.agents.dependencies import get_investigation_repository
from app.common.config import config
from app.incidents.dependencies import (
    close_incident_repository,
    get_incident_repository,
    set_custom_incident_db_path,
)
from app.knowledge.dependencies import reset_knowledge_state
from app.main import app
from app.projects.dependencies import (
    close_project_store,
    get_project_store,
    reset_project_state,
    set_custom_project_db_path,
)
from app.projects.models import Project, ProjectStatus
from app.projects.storage import SqliteProjectStore
from app.retrieval.scanner import SourceScanner
from app.telemetry.dependencies import get_evidence_repository
from app.telemetry.models import Evidence, EvidenceType
from app.watcher.dependencies import reset_watcher_state

client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_all_state(tmp_path: Path) -> Generator[None, None, None]:
    """Ensure complete test isolation across all SentinelOps components using an isolated temporary SQLite DB."""
    test_db = str(tmp_path / "sentinelops_test.db")
    set_custom_project_db_path(test_db)
    set_custom_incident_db_path(test_db)

    app.dependency_overrides.clear()
    reset_project_state()
    reset_knowledge_state()
    get_investigation_repository().clear()
    get_incident_repository().clear()
    get_evidence_repository().clear()
    reset_watcher_state()

    # Safety assertion: verify the store binds to test_db, never production DB
    store = get_project_store()
    prod_db = str(Path("runtime/sentinelops.db").resolve())
    assert store.db_path != prod_db, f"Test project store must not bind to live DB: {store.db_path}"
    assert store.db_path == str(Path(test_db).resolve()), f"Store path mismatch: {store.db_path}"

    yield

    app.dependency_overrides.clear()
    reset_project_state()
    close_project_store()
    close_incident_repository()
    set_custom_project_db_path(None)
    set_custom_incident_db_path(None)
    reset_knowledge_state()
    get_investigation_repository().clear()
    get_evidence_repository().clear()
    reset_watcher_state()


def _init_git_repo(path: Path) -> None:
    """Helper to initialize a real git repo with a commit."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@sentinelops.local"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "SentinelOps Test"], cwd=str(path), check=True, capture_output=True)
    readme = path / "README.md"
    readme.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True, capture_output=True)


# ==============================================================================
# 1. Workspace Path Validation
# ==============================================================================

def test_workspace_path_validation_nonexistent() -> None:
    """Nonexistent workspace directory must return 400 Bad Request."""
    res = client.post(
        "/projects",
        json={
            "project_id": "nonexistent-proj",
            "name": "Nonexistent",
            "workspace_path": "Z:/definitely/not/a/real/path/12345",
        },
    )
    assert res.status_code == 400
    assert "Workspace path does not exist" in res.json()["detail"]


def test_workspace_path_validation_file_not_dir(tmp_path: Path) -> None:
    """Targeting a regular file instead of a directory must return 400 Bad Request."""
    sample_file = tmp_path / "hello.txt"
    sample_file.write_text("hello", encoding="utf-8")
    res = client.post(
        "/projects",
        json={
            "project_id": "file-proj",
            "name": "File Project",
            "workspace_path": str(sample_file),
        },
    )
    assert res.status_code == 400
    assert "is a file, not a directory" in res.json()["detail"]


def test_workspace_path_validation_root_drive() -> None:
    """Filesystem root drive must be blocked from onboarding with 400 Bad Request."""
    root_drive = "C:\\" if os.name == "nt" else "/"
    res = client.post(
        "/projects",
        json={
            "project_id": "root-proj",
            "name": "Root Project",
            "workspace_path": root_drive,
        },
    )
    assert res.status_code == 400
    assert "Filesystem root cannot be used as project workspace" in res.json()["detail"]


# ==============================================================================
# 2. OS-aware Normalization & Duplicate Registration Checks
# ==============================================================================

def test_duplicate_project_id_returns_409(tmp_path: Path) -> None:
    """Registering two different workspaces under the same project_id returns 409 Conflict."""
    dir1 = tmp_path / "ws1"
    dir1.mkdir()
    (dir1 / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    dir2 = tmp_path / "ws2"
    dir2.mkdir()
    (dir2 / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    res1 = client.post(
        "/projects",
        json={"project_id": "duplicate-id", "name": "Project 1", "workspace_path": str(dir1)},
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/projects",
        json={"project_id": "duplicate-id", "name": "Project 2", "workspace_path": str(dir2)},
    )
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"]


def test_duplicate_workspace_path_returns_409_including_case_variation(tmp_path: Path) -> None:
    """Registering the same workspace under different project IDs returns 409 Conflict.
    Also verifies Windows case-folding and trailing-slash normalization."""
    ws = tmp_path / "service_a"
    ws.mkdir()
    (ws / "main.py").write_text("def start(): pass\n", encoding="utf-8")

    # First registration
    res1 = client.post(
        "/projects",
        json={"project_id": "proj-a", "name": "Service A", "workspace_path": str(ws)},
    )
    assert res1.status_code == 201

    # Second registration with trailing slash
    res2 = client.post(
        "/projects",
        json={"project_id": "proj-b", "name": "Service B", "workspace_path": str(ws) + "/"},
    )
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"]

    # If on Windows, case variation must also resolve to the same normalized path and trigger 409
    if os.name == "nt":
        case_varied_path = str(ws).upper()
        res3 = client.post(
            "/projects",
            json={"project_id": "proj-c", "name": "Service C", "workspace_path": case_varied_path},
        )
        assert res3.status_code == 409
        assert "already registered" in res3.json()["detail"]


# ==============================================================================
# 3. Project Onboarding Lifecycle (Git vs Non-Git)
# ==============================================================================

def test_register_git_project_lifecycle(tmp_path: Path) -> None:
    """Full onboarding lifecycle for a Git repository with routes, symbols, and configs."""
    ws = tmp_path / "orders_service"
    ws.mkdir()
    _init_git_repo(ws)

    # Add FastAPI route and business logic
    route_file = ws / "api.py"
    route_file.write_text(
        """from fastapi import APIRouter
router = APIRouter()

@router.post("/orders/checkout")
def checkout_order(order_id: str):
    \"\"\"Process checkout order.\"\"\"
    return {"status": "ok"}
""",
        encoding="utf-8",
    )
    # Add pyproject.toml
    config_file = ws / "pyproject.toml"
    config_file.write_text("[project]\nname = 'orders_service'\nversion = '1.0.0'\n", encoding="utf-8")

    res = client.post(
        "/projects",
        json={
            "project_id": "orders-git",
            "name": "Orders Service",
            "description": "Handles payment and checkout",
            "workspace_path": str(ws),
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == "orders-git"
    assert data["status"] == "ready"
    assert data["is_git"] is True
    assert data["default_branch"] in ("main", "master")
    assert data["index_version"] is not None
    assert data["last_indexed_at"] is not None

    # Verify GET /projects and GET /projects/{project_id}
    list_res = client.get("/projects")
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1
    assert list_res.json()[0]["project_id"] == "orders-git"

    get_res = client.get("/projects/orders-git")
    assert get_res.status_code == 200
    assert get_res.json()["project_id"] == "orders-git"

    # Verify GET /projects/{project_id}/knowledge
    know_res = client.get("/projects/orders-git/knowledge")
    assert know_res.status_code == 200
    know_data = know_res.json()
    assert know_data["project_id"] == "orders-git"
    assert know_data["files_count"] >= 1
    assert know_data["chunks_count"] >= 1
    assert len(know_data["routes"]) >= 1
    assert know_data["routes"][0]["path"] == "/orders/checkout"
    assert len(know_data["config_files"]) >= 1
    assert any(c["file_name"] == "pyproject.toml" for c in know_data["config_files"])


def test_register_source_only_project_lifecycle(tmp_path: Path) -> None:
    """Non-Git directory must onboard cleanly with is_git=False and default_branch=None."""
    ws = tmp_path / "legacy_scripts"
    ws.mkdir()
    script = ws / "worker.py"
    script.write_text("def run_batch(): pass\n", encoding="utf-8")

    res = client.post(
        "/projects",
        json={
            "project_id": "legacy-source",
            "name": "Legacy Scripts",
            "workspace_path": str(ws),
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == "legacy-source"
    assert data["status"] == "ready"
    assert data["is_git"] is False
    assert data["default_branch"] is None

    know_res = client.get("/projects/legacy-source/knowledge")
    assert know_res.status_code == 200
    assert know_res.json()["files_count"] == 1


# ==============================================================================
# 4. Scanner Enhancements (Exclusions, Max Files Cap, Max File Size, Symlinks)
# ==============================================================================

def test_scanner_exclusions_and_deterministic_caps(tmp_path: Path) -> None:
    """Scanner must exclude ignored folders, enforce max_file_size, and sort deterministically before cap."""
    ws = tmp_path / "scanner_test"
    ws.mkdir()

    # Ignored directory files
    (ws / ".venv").mkdir()
    (ws / ".venv" / "venv_script.py").write_text("print(1)", encoding="utf-8")
    (ws / "node_modules").mkdir()
    (ws / "node_modules" / "pkg.py").write_text("print(1)", encoding="utf-8")
    (ws / ".git").mkdir()
    (ws / ".git" / "hook.py").write_text("print(1)", encoding="utf-8")

    # Oversized file
    big_file = ws / "huge_data.py"
    big_file.write_text("x = 1\n" * 1000, encoding="utf-8")
    big_size = big_file.stat().st_size

    # Valid regular files
    (ws / "z_file.py").write_text("def z(): pass\n", encoding="utf-8")
    (ws / "a_file.py").write_text("def a(): pass\n", encoding="utf-8")
    (ws / "m_file.py").write_text("def m(): pass\n", encoding="utf-8")

    # Scanner configured with max_file_size smaller than huge_data.py
    scanner = SourceScanner(
        max_files=2,  # Cap to 2 files after deterministic sorting
        max_file_size=big_size - 10,
    )
    scanned_results = scanner.scan(ws)

    # Files must exclude .venv, node_modules, .git, huge_data.py
    # From ['a_file.py', 'm_file.py', 'z_file.py'], deterministically top 2 are ['a_file.py', 'm_file.py']
    file_rel_paths = [rel_path.split("/")[-1] for rel_path, _ in scanned_results]
    assert file_rel_paths == ["a_file.py", "m_file.py"]


def test_scanner_skips_external_symlinks_safely(tmp_path: Path) -> None:
    """External symlinks pointing outside workspace root must be skipped."""
    external_dir = tmp_path / "outside_dir"
    external_dir.mkdir()
    (external_dir / "secret.py").write_text("def secret(): pass\n", encoding="utf-8")

    ws = tmp_path / "safe_workspace"
    ws.mkdir()
    (ws / "local.py").write_text("def local(): pass\n", encoding="utf-8")

    symlink_target = ws / "linked_ext"
    symlink_created = False
    try:
        os.symlink(str(external_dir), str(symlink_target), target_is_directory=True)
        symlink_created = True
    except (OSError, NotImplementedError):
        pass

    scanner = SourceScanner()
    scanned_results = scanner.scan(ws)
    scanned_rel = [rel_path for rel_path, _ in scanned_results]

    assert any("local.py" in s for s in scanned_rel)
    if symlink_created:
        assert not any("secret.py" in s for s in scanned_rel)


# ==============================================================================
# 5. Persistence Across Restarts & Lazy Hydration
# ==============================================================================

def test_persistence_across_store_recreation(tmp_path: Path) -> None:
    """SqliteProjectStore retains project metadata across store re-instantiations."""
    db_file = tmp_path / "projects_test.db"
    store1 = SqliteProjectStore(db_path=db_file)

    ws = tmp_path / "repo1"
    ws.mkdir()
    (ws / "app.py").write_text("def run(): pass\n", encoding="utf-8")

    now = datetime.now(timezone.utc)
    proj = Project(
        project_id="persisted-proj",
        name="Persisted Project",
        workspace_path=ws.as_posix(),
        normalized_path=os.path.normcase(os.path.normpath(str(ws))),
        is_git=False,
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
        last_indexed_at=now,
        index_version="hash-v1",
    )
    store1.create_project(proj)

    store2 = SqliteProjectStore(db_path=db_file)
    retrieved = store2.get_project("persisted-proj")
    assert retrieved is not None
    assert retrieved.name == "Persisted Project"
    assert retrieved.index_version == "hash-v1"
    assert retrieved.status == ProjectStatus.READY


def test_lazy_hydration_on_restart(tmp_path: Path) -> None:
    """After a process restart (in-memory indices cleared), querying search lazily hydrates index."""
    ws = tmp_path / "lazy_repo"
    ws.mkdir()
    (ws / "calc.py").write_text("def calculate_lazy_sum(a, b):\n    return a + b\n", encoding="utf-8")

    res = client.post(
        "/projects",
        json={"project_id": "lazy-proj", "name": "Lazy Project", "workspace_path": str(ws)},
    )
    assert res.status_code == 201

    # Simulate restart by clearing in-memory knowledge cache
    reset_knowledge_state()

    search_res = client.post(
        "/projects/lazy-proj/search",
        json={"query": "calculate_lazy_sum"},
    )
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] >= 1
    assert any("calculate_lazy_sum" in item["content"] for item in search_data["results"])


# ==============================================================================
# 6. Multi-Project Search Isolation
# ==============================================================================

def test_multi_project_search_isolation(tmp_path: Path) -> None:
    """Project A and Project B indexes remain strictly isolated."""
    ws_a = tmp_path / "project_alpha"
    ws_a.mkdir()
    (ws_a / "alpha.py").write_text("def alpha_unique_calculate():\n    return 'alpha'\n", encoding="utf-8")

    ws_b = tmp_path / "project_beta"
    ws_b.mkdir()
    (ws_b / "beta.py").write_text("def beta_different_render():\n    return 'beta'\n", encoding="utf-8")

    res_a = client.post("/projects", json={"project_id": "proj-alpha", "name": "Alpha", "workspace_path": str(ws_a)})
    res_b = client.post("/projects", json={"project_id": "proj-beta", "name": "Beta", "workspace_path": str(ws_b)})
    assert res_a.status_code == 201
    assert res_b.status_code == 201

    # Search for alpha in Project A -> matches
    res_a_alpha = client.post("/projects/proj-alpha/search", json={"query": "alpha_unique_calculate"})
    assert res_a_alpha.status_code == 200
    assert res_a_alpha.json()["total"] >= 1

    # Search for alpha in Project B -> 0 matches
    res_b_alpha = client.post("/projects/proj-beta/search", json={"query": "alpha_unique_calculate"})
    assert res_b_alpha.status_code == 200
    assert res_b_alpha.json()["total"] == 0

    # Search for beta in Project B -> matches
    res_b_beta = client.post("/projects/proj-beta/search", json={"query": "beta_different_render"})
    assert res_b_beta.status_code == 200
    assert res_b_beta.json()["total"] >= 1

    # Search for beta in Project A -> 0 matches
    res_a_beta = client.post("/projects/proj-alpha/search", json={"query": "beta_different_render"})
    assert res_a_beta.status_code == 200
    assert res_a_beta.json()["total"] == 0


# ==============================================================================
# 7. Reindexing Lifecycle & Error Preservation
# ==============================================================================

def test_reindex_lifecycle(tmp_path: Path) -> None:
    """Reindexing updates index when files are added, modified, or removed."""
    ws = tmp_path / "dynamic_repo"
    ws.mkdir()
    file1 = ws / "version.py"
    file1.write_text("def get_version_v1(): return 1\n", encoding="utf-8")

    client.post("/projects", json={"project_id": "dyn-proj", "name": "Dynamic", "workspace_path": str(ws)})
    v1_knowledge = client.get("/projects/dyn-proj/knowledge").json()
    v1_hash = v1_knowledge["index_version"]

    # Modify file and add new file
    file1.write_text("def get_version_v2(): return 2\n", encoding="utf-8")
    file2 = ws / "routes.py"
    file2.write_text(
        "from fastapi import APIRouter\nr = APIRouter()\n@r.get('/new-route')\ndef handle(): pass\n",
        encoding="utf-8",
    )

    reindex_res = client.post("/projects/dyn-proj/reindex")
    assert reindex_res.status_code == 200
    reindex_data = reindex_res.json()
    assert reindex_data["index_version"] != v1_hash
    assert len(reindex_data["routes"]) >= 1
    assert reindex_data["files_count"] == 2

    # Verify search finds new version
    s_res = client.post("/projects/dyn-proj/search", json={"query": "get_version_v2"})
    assert s_res.json()["total"] >= 1


def test_git_working_tree_change_without_commit_updates_index_version(tmp_path: Path) -> None:
    """Working-tree changes without a Git commit must update index_version upon reindex and restart."""
    ws = tmp_path / "git_worktree_repo"
    ws.mkdir()
    _init_git_repo(ws)

    # Initial committed code
    init_file = ws / "orders.py"
    init_file.write_text("class OrderService:\n    def process(self): return 'ok'\n", encoding="utf-8")
    subprocess.run(["git", "add", "orders.py"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Add order service"], cwd=str(ws), check=True, capture_output=True)

    reg_res = client.post(
        "/projects",
        json={"project_id": "git-wt-proj", "name": "Git Worktree", "workspace_path": str(ws)},
    )
    assert reg_res.status_code == 201
    v1 = reg_res.json()["index_version"]
    assert v1.startswith("v1-")

    # Add new uncommitted file to working tree
    uncommitted_file = ws / "refund.py"
    uncommitted_file.write_text(
        "class RefundService:\n    def refund(self):\n        return 'ALPHA_AFTER_RESTART'\n",
        encoding="utf-8",
    )

    # 1. Test explicit reindex advances version
    reindex_res = client.post("/projects/git-wt-proj/reindex")
    assert reindex_res.status_code == 200
    v2 = reindex_res.json()["index_version"]
    assert v2 != v1

    # Search finds the new uncommitted class
    search_res = client.post("/projects/git-wt-proj/search", json={"query": "RefundService"})
    assert search_res.status_code == 200
    assert search_res.json()["total"] >= 1
    assert any("RefundService" in item["content"] for item in search_res.json()["results"])

    # 2. Test restart / lazy hydration also maintains the new version
    reset_knowledge_state()
    get_res = client.get("/projects/git-wt-proj/knowledge")
    assert get_res.status_code == 200
    v_hydrated = get_res.json()["index_version"]
    assert v_hydrated == v2

    # Modify uncommitted file content without changing line numbers or Git HEAD
    uncommitted_file.write_text(
        "class RefundService:\n    def refund(self):\n        return 'ALPHA_MODIFIED_CONTENT'\n",
        encoding="utf-8",
    )
    reindex_res3 = client.post("/projects/git-wt-proj/reindex")
    assert reindex_res3.status_code == 200
    v3 = reindex_res3.json()["index_version"]
    assert v3 != v2
    assert v3 != v1


def test_index_version_determinism_on_unchanged_repo(tmp_path: Path) -> None:
    """Indexing an unchanged repository multiple times produces identical index_version."""
    ws = tmp_path / "det_repo"
    ws.mkdir()
    _init_git_repo(ws)
    (ws / "app.py").write_text("def stable_handler(): return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Add app"], cwd=str(ws), check=True, capture_output=True)

    reg_res = client.post("/projects", json={"project_id": "det-proj", "name": "Det", "workspace_path": str(ws)})
    assert reg_res.status_code == 201
    v1 = reg_res.json()["index_version"]

    # Reindex unchanged
    reindex_res = client.post("/projects/det-proj/reindex")
    assert reindex_res.status_code == 200
    v2 = reindex_res.json()["index_version"]
    assert v1 == v2

    # Restart and lazy hydrate
    reset_knowledge_state()
    know_res = client.get("/projects/det-proj/knowledge")
    assert know_res.status_code == 200
    v3 = know_res.json()["index_version"]
    assert v1 == v3


def test_git_head_change_updates_index_version(tmp_path: Path) -> None:
    """Creating a new Git commit advances index_version even if code content is unchanged."""
    ws = tmp_path / "head_change_repo"
    ws.mkdir()
    _init_git_repo(ws)
    (ws / "main.py").write_text("def run(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "main.py"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Commit 1"], cwd=str(ws), check=True, capture_output=True)

    reg_res = client.post("/projects", json={"project_id": "head-proj", "name": "Head", "workspace_path": str(ws)})
    assert reg_res.status_code == 201
    v1 = reg_res.json()["index_version"]

    # Create a new commit touching a non-code file (e.g. docs) so code chunks stay identical
    (ws / "notes.txt").write_text("extra commit notes\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.txt"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Commit 2"], cwd=str(ws), check=True, capture_output=True)

    reindex_res = client.post("/projects/head-proj/reindex")
    assert reindex_res.status_code == 200
    v2 = reindex_res.json()["index_version"]
    assert v2 != v1


def test_config_file_changes_update_index_version(tmp_path: Path) -> None:
    """Adding, modifying, or removing a discovered configuration file advances index_version."""
    ws = tmp_path / "config_version_repo"
    ws.mkdir()
    (ws / "main.py").write_text("def run(): pass\n", encoding="utf-8")

    # 1. Onboard initial repo without config file
    reg_res = client.post(
        "/projects",
        json={"project_id": "cfg-proj", "name": "Config Project", "workspace_path": str(ws)},
    )
    assert reg_res.status_code == 201
    v1 = reg_res.json()["index_version"]

    # Reindex unchanged -> deterministic identical version
    reindex_same = client.post("/projects/cfg-proj/reindex")
    assert reindex_same.status_code == 200
    assert reindex_same.json()["index_version"] == v1

    # 2. Add pyproject.toml -> index_version must change
    config_file = ws / "pyproject.toml"
    config_file.write_text("[project]\nname = 'cfg-proj'\nversion = '1.0.0'\n", encoding="utf-8")

    reindex_add = client.post("/projects/cfg-proj/reindex")
    assert reindex_add.status_code == 200
    v2 = reindex_add.json()["index_version"]
    assert v2 != v1
    assert any(c["file_name"] == "pyproject.toml" for c in reindex_add.json()["config_files"])

    # 3. Modify pyproject.toml content -> index_version must change
    config_file.write_text("[project]\nname = 'cfg-proj'\nversion = '2.0.0'\n", encoding="utf-8")
    reindex_mod = client.post("/projects/cfg-proj/reindex")
    assert reindex_mod.status_code == 200
    v3 = reindex_mod.json()["index_version"]
    assert v3 != v2
    assert v3 != v1

    # 4. Remove pyproject.toml -> index_version must change again
    config_file.unlink()
    reindex_del = client.post("/projects/cfg-proj/reindex")
    assert reindex_del.status_code == 200
    v4 = reindex_del.json()["index_version"]
    assert v4 != v3
    assert v4 == v1


def test_fatal_reindex_preserves_previous_good_index(tmp_path: Path) -> None:
    """A failed reindex keeps the previous good index searchable and records last_index_error."""
    ws = tmp_path / "stable_repo"
    ws.mkdir()
    (ws / "core.py").write_text("def core_stable_logic(): return 42\n", encoding="utf-8")

    reg_res = client.post("/projects", json={"project_id": "stable-proj", "name": "Stable", "workspace_path": str(ws)})
    assert reg_res.status_code == 201
    init_version = reg_res.json()["index_version"]

    # Search works initially
    pre_search = client.post("/projects/stable-proj/search", json={"query": "core_stable_logic"})
    assert pre_search.json()["total"] >= 1

    # Simulate fatal indexing error by temporarily moving the directory away
    moved_ws = tmp_path / "stable_repo_moved"
    ws.rename(moved_ws)

    try:
        fail_reindex = client.post("/projects/stable-proj/reindex")
        assert fail_reindex.status_code == 422

        # Check project metadata: status remains READY, index_version preserved, last_index_error set
        proj_res = client.get("/projects/stable-proj")
        assert proj_res.status_code == 200
        proj_data = proj_res.json()
        assert proj_data["status"] == "ready"
        assert proj_data["index_version"] == init_version
        assert proj_data["last_index_error"] is not None
        assert "missing or unreadable" in proj_data["last_index_error"]

        # Crucially: previous in-memory index is preserved and STILL searchable!
        post_search = client.post("/projects/stable-proj/search", json={"query": "core_stable_logic"})
        assert post_search.json()["total"] >= 1
    finally:
        if moved_ws.exists():
            moved_ws.rename(ws)


# ==============================================================================
# 8. Investigation Project Scoping & Isolation
# ==============================================================================

def test_investigation_project_scoped_retrieval(tmp_path: Path) -> None:
    """An incident for an onboarded project retrieves only that project's code."""
    ws = tmp_path / "scoped_repo"
    ws.mkdir()
    _init_git_repo(ws)
    (ws / "billing.py").write_text("def charge_customer(card_id: str):\n    raise RuntimeError('card_declined')\n", encoding="utf-8")

    # Onboard project
    reg = client.post("/projects", json={"project_id": "billing-app", "name": "Billing", "workspace_path": str(ws)})
    assert reg.status_code == 201

    # Create incident with project_id="billing-app"
    inc_res = client.post(
        "/incidents",
        json={
            "title": "Card charge error",
            "summary": "card_declined inside charge_customer",
            "severity": "high",
            "service": "billing-app",
            "environment": "production",
            "project_id": "billing-app",
        },
    )
    assert inc_res.status_code == 201
    inc_id = inc_res.json()["id"]

    # Ingest verified runtime evidence
    ev_repo = get_evidence_repository()
    now = datetime.now(timezone.utc)
    evidence = Evidence(
        id=str(uuid.uuid4()),
        incident_id=inc_id,
        type=EvidenceType.RUNTIME_LOG,
        source="billing.py",
        timestamp=now,
        service="billing-app",
        request_id="req-test-12345",
        level="ERROR",
        event="card_charge_failed",
        message="RuntimeError: card_declined in charge_customer billing.py",
        endpoint="/billing/charge",
        exception_type="RuntimeError",
        created_at=now,
    )
    ev_repo.create(evidence)

    # Trigger investigation
    inv_res = client.post(f"/incidents/{inc_id}/investigate")
    assert inv_res.status_code == 200
    inv_data = inv_res.json()
    assert inv_data["status"] == "completed"

    # Verify retrieved code chunks come from the project's workspace
    code_results = inv_data["code_results"]
    assert len(code_results) >= 1
    assert any("billing.py" in c["file_path"] for c in code_results)


def test_investigation_explicit_unknown_project_no_fallback() -> None:
    """An incident for an explicit unknown project MUST NOT fall back to legacy repo."""
    inc_res = client.post(
        "/incidents",
        json={
            "title": "Unknown Project Incident",
            "summary": "Some error occurred",
            "severity": "medium",
            "service": "mystery-service",
            "environment": "production",
            "project_id": "completely-unknown-project",
        },
    )
    assert inc_res.status_code == 201
    inc_id = inc_res.json()["id"]

    ev_repo = get_evidence_repository()
    now = datetime.now(timezone.utc)
    evidence = Evidence(
        id=str(uuid.uuid4()),
        incident_id=inc_id,
        type=EvidenceType.RUNTIME_LOG,
        source="mystery.py",
        timestamp=now,
        service="mystery-service",
        request_id="req-mystery-999",
        level="ERROR",
        event="mystery_failure",
        message="Failure in mystery endpoint",
        endpoint="/mystery/endpoint",
        exception_type="MysteryError",
        created_at=now,
    )
    ev_repo.create(evidence)

    inv_res = client.post(f"/incidents/{inc_id}/investigate")
    assert inv_res.status_code == 200
    inv_data = inv_res.json()

    assert len(inv_data["code_results"]) == 0
    assert len(inv_data["git_context"]) == 0
    assert any("not onboarded" in err for err in inv_data["errors"])


def test_investigation_legacy_incident_compatibility() -> None:
    """An incident with project_id='default' falls back safely to legacy RetrievalService/GitService."""
    inc_res = client.post(
        "/incidents",
        json={
            "title": "Legacy Incident",
            "summary": "Failure in demo repository",
            "severity": "medium",
            "service": "demo-service",
            "environment": "production",
            # project_id omitted -> defaults to "default"
        },
    )
    assert inc_res.status_code == 201
    inc_data = inc_res.json()
    assert inc_data["project_id"] == "default"
    inc_id = inc_data["id"]

    ev_repo = get_evidence_repository()
    now = datetime.now(timezone.utc)
    evidence = Evidence(
        id=str(uuid.uuid4()),
        incident_id=inc_id,
        type=EvidenceType.RUNTIME_LOG,
        source="demo.py",
        timestamp=now,
        service="demo-service",
        request_id="req-legacy-111",
        level="ERROR",
        event="division_by_zero",
        message="ZeroDivisionError in calculate_discount",
        endpoint="/discounts",
        exception_type="ZeroDivisionError",
        created_at=now,
    )
    ev_repo.create(evidence)

    inv_res = client.post(f"/incidents/{inc_id}/investigate")
    assert inv_res.status_code == 200
    assert inv_res.json()["status"] == "completed"


# ==============================================================================
# 9. Incident project_id Propagation & Telemetry Normalization
# ==============================================================================

def test_incident_project_id_propagation_from_telemetry() -> None:
    """Telemetry ingested via Watcher propagates project_id to the automatically created incident."""
    payload = {
        "project_id": "payments-core",
        "service": "payment-worker",
        "signal_type": "log",
        "event_type": "database_deadlock",
        "message": "Deadlock detected during transaction",
        "level": "ERROR",
        "request_id": "req-deadlock-999",
        "exception_type": "DeadlockError",
        "endpoint": "/checkout/commit",
    }
    resp = client.post("/watcher/events", json=payload)
    assert resp.status_code == 202

    incidents_res = client.get("/incidents")
    assert incidents_res.status_code == 200
    incidents = incidents_res.json()
    assert len(incidents) >= 1
    target = next((inc for inc in incidents if inc.get("service") == "payment-worker"), None)
    assert target is not None
    assert target["project_id"] == "payments-core"


def test_incident_creation_normalizes_none_to_default() -> None:
    """Explicitly passing null/None for project_id normalizes to 'default'."""
    res = client.post(
        "/incidents",
        json={
            "title": "Null project incident",
            "summary": "Testing project_id normalization",
            "severity": "low",
            "service": "null-test",
            "environment": "dev",
            "project_id": None,
        },
    )
    assert res.status_code == 201
    assert res.json()["project_id"] == "default"


# ==============================================================================
# 10. Legacy Repository Endpoints Compatibility
# ==============================================================================

def test_legacy_repository_endpoints_compatibility() -> None:
    """Stage 4/5 endpoints continue to operate normally with no onboarded projects."""
    status_res = client.get("/repository/status")
    assert status_res.status_code == 200

    search_res = client.post("/repository/search", json={"query": "order"})
    # Status code is either 200 or 409 depending on whether repository has been indexed
    assert search_res.status_code in (200, 409)


# ==============================================================================
# 11. Durable Store Lifecycles and Process Restart Simulation
# ==============================================================================

def test_durable_registration_across_connection_lifecycles(tmp_path: Path) -> None:
    """Project registered in Store 1 survives full store closure and is readable by a new Store 2."""
    db_file = str(tmp_path / "durable_registration.db")
    store_1 = SqliteProjectStore(db_path=db_file)

    now = datetime.now(timezone.utc)
    ws_dir = tmp_path / "durable_ws_1"
    ws_dir.mkdir()
    p1 = Project(
        project_id="proj-durable-1",
        name="Durable One",
        description="First durable test project",
        workspace_path=str(ws_dir),
        normalized_path=os.path.normcase(os.path.normpath(str(ws_dir.resolve()))),
        is_git=True,
        default_branch="main",
        status=ProjectStatus.READY,
        created_at=now,
        updated_at=now,
    )

    store_1.create_project(p1)

    # Fully close and discard the original store/connection
    store_1.close()
    del store_1

    # Create a completely new store against the same DB file
    store_2 = SqliteProjectStore(db_path=db_file)
    loaded = store_2.get_project("proj-durable-1")

    assert loaded is not None
    assert loaded.project_id == "proj-durable-1"
    assert loaded.name == "Durable One"
    assert loaded.description == "First durable test project"
    assert loaded.workspace_path == str(ws_dir)
    assert loaded.is_git is True
    assert loaded.default_branch == "main"
    assert loaded.status == ProjectStatus.READY
    assert loaded.created_at == now
    assert loaded.updated_at == now

    store_2.close()


def test_durable_updates_across_connection_lifecycles(tmp_path: Path) -> None:
    """Project updates (status, index_version, last_indexed_at, last_index_error) survive store destruction."""
    db_file = str(tmp_path / "durable_updates.db")
    store_1 = SqliteProjectStore(db_path=db_file)

    now = datetime.now(timezone.utc)
    ws_dir = tmp_path / "durable_ws_2"
    ws_dir.mkdir()
    p = Project(
        project_id="proj-durable-2",
        name="Durable Two",
        workspace_path=str(ws_dir),
        normalized_path=os.path.normcase(os.path.normpath(str(ws_dir.resolve()))),
        is_git=False,
        status=ProjectStatus.REGISTERED,
        created_at=now,
        updated_at=now,
    )
    store_1.create_project(p)

    # Apply updates
    indexed_time = datetime.now(timezone.utc)
    p.status = ProjectStatus.READY
    p.index_version = "v1-09ef91ac-d830bf21"
    p.last_indexed_at = indexed_time
    p.last_index_error = "Transient warning recorded"
    store_1.update_project(p)

    # Destroy the first store/connection
    store_1.close()
    del store_1

    # Recreate store using the same DB file
    store_2 = SqliteProjectStore(db_path=db_file)
    loaded = store_2.get_project("proj-durable-2")

    assert loaded is not None
    assert loaded.project_id == "proj-durable-2"
    assert loaded.status == ProjectStatus.READY
    assert loaded.index_version == "v1-09ef91ac-d830bf21"
    assert loaded.last_indexed_at == indexed_time
    assert loaded.last_index_error == "Transient warning recorded"

    store_2.close()


def test_durable_api_recreation_across_process_simulation(tmp_path: Path) -> None:
    """Onboarded project survives API dependency recreation, survives process shutdown simulation, and lazy hydrates."""
    ws = tmp_path / "durable_api_workspace"
    ws.mkdir()
    (ws / "service.py").write_text("def durable_process_task():\n    return 'survives_restart'\n", encoding="utf-8")

    # 1. Onboard via POST /projects
    res = client.post(
        "/projects",
        json={"project_id": "proj-durable-api", "name": "Durable API Proj", "workspace_path": str(ws)},
    )
    assert res.status_code == 201
    assert res.json()["status"] == "ready"

    # 2. Simulate complete process restart: close store and clear in-memory caches
    close_project_store()
    reset_knowledge_state()

    # 3. GET /projects returns the persisted project without re-registering
    list_res = client.get("/projects")
    assert list_res.status_code == 200
    projects = list_res.json()
    assert any(p["project_id"] == "proj-durable-api" for p in projects)
    target = next(p for p in projects if p["project_id"] == "proj-durable-api")
    assert target["status"] == "ready"

    # 4. GET /projects/{id} returns the project
    get_res = client.get("/projects/proj-durable-api")
    assert get_res.status_code == 200
    assert get_res.json()["project_id"] == "proj-durable-api"

    # 5. POST /projects/{id}/search triggers lazy hydration from persisted workspace
    search_res = client.post("/projects/proj-durable-api/search", json={"query": "durable_process_task"})
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["total"] >= 1
    assert any("durable_process_task" in item["content"] for item in search_data["results"])


def test_test_environment_never_binds_to_production_database() -> None:
    """Safety regression test: automated tests must never bind project store to live runtime/sentinelops.db."""
    store = get_project_store()
    prod_db = str(Path("runtime/sentinelops.db").resolve())
    assert store.db_path != prod_db, (
        f"Test project store is bound to production database: {store.db_path}"
    )
    assert "sentinelops_test.db" in store.db_path
    assert not store.db_path.endswith(os.path.join("runtime", "sentinelops.db"))
