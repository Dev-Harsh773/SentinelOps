"""Automated tests for Stage 5 Git change intelligence.

All tests operate strictly on isolated temporary Git repositories created via pytest tmp_path.
The real SentinelOps repository is NEVER mutated by tests.
"""

from datetime import datetime, timezone
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repository.client import GitClient
from app.repository.dependencies import get_git_service
from app.repository.models import (
    GitCommitReferenceInvalidError,
    GitFilePathInvalidError,
    GitRepositoryInvalidError,
    GitRepositoryNotFoundError,
)
from app.repository.service import GitService

client = TestClient(app)


# =====================================================================
# Fixture: Isolated Temporary Git Repository
# =====================================================================


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Creates a temporary Git repository with controlled, deterministic commit history.

    History:
    - Commit 1 (root): Add order service (demo_app/services/order_service.py)
    - Commit 2: Modify order processing (demo_app/services/order_service.py)
    - Commit 3: Add unrelated module (demo_app/services/unrelated.py)
    - Commit 4: Rename unrelated module (demo_app/services/unrelated.py -> demo_app/services/renamed.py)
    - Commit 5: Delete renamed module (demo_app/services/renamed.py)
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    def run_git(args: list[str]) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        return res.stdout.strip()

    run_git(["init"])
    run_git(["config", "user.name", "SentinelOps Test"])
    run_git(["config", "user.email", "sentinelops-test@example.com"])

    # Commit 1: Root commit
    services_dir = repo_dir / "demo_app" / "services"
    services_dir.mkdir(parents=True)
    order_file = services_dir / "order_service.py"
    order_file.write_text("class OrderService:\n    def create_order(self):\n        return True\n", encoding="utf-8")
    run_git(["add", "."])
    run_git(["commit", "-m", "Add order service"])
    c1_hash = run_git(["rev-parse", "HEAD"])

    # Commit 2: Modify order processing
    order_file.write_text(
        "class OrderService:\n    def create_order(self):\n        raise OrderProcessingError('Failed')\n",
        encoding="utf-8",
    )
    run_git(["add", "."])
    run_git(["commit", "-m", "Modify order processing"])
    c2_hash = run_git(["rev-parse", "HEAD"])

    # Commit 3: Add unrelated module
    unrelated_file = services_dir / "unrelated.py"
    unrelated_file.write_text("def unrelated_func():\n    return 42\n", encoding="utf-8")
    run_git(["add", "."])
    run_git(["commit", "-m", "Add unrelated module"])
    c3_hash = run_git(["rev-parse", "HEAD"])

    # Commit 4: Rename unrelated module
    run_git(["mv", "demo_app/services/unrelated.py", "demo_app/services/renamed.py"])
    run_git(["commit", "-m", "Rename unrelated module"])
    c4_hash = run_git(["rev-parse", "HEAD"])

    # Commit 5: Delete renamed module
    run_git(["rm", "demo_app/services/renamed.py"])
    run_git(["commit", "-m", "Delete renamed module"])
    c5_hash = run_git(["rev-parse", "HEAD"])

    hashes = {
        "c1": c1_hash,
        "c2": c2_hash,
        "c3": c3_hash,
        "c4": c4_hash,
        "c5": c5_hash,
    }

    return repo_dir, hashes


@pytest.fixture
def override_git_service(temp_git_repo):
    """Overrides FastAPI GitService dependency to point to the temporary Git repository."""
    repo_dir, hashes = temp_git_repo
    git_client = GitClient(repository_path=str(repo_dir))
    git_service = GitService(client=git_client, repository_name="sentinelops-test")

    app.dependency_overrides[get_git_service] = lambda: git_service
    yield repo_dir, hashes, git_service
    app.dependency_overrides.pop(get_git_service, None)


# =====================================================================
# Unit Tests: Repository Validation
# =====================================================================


def test_repository_validation_success(temp_git_repo):
    """Valid Git repository passes validation."""
    repo_dir, _ = temp_git_repo
    client_git = GitClient(repository_path=str(repo_dir))
    # Should not raise
    client_git.validate_repository()


def test_repository_validation_nonexistent_directory(tmp_path: Path):
    """Nonexistent repository path raises GitRepositoryNotFoundError and API returns 500."""
    nonexistent = tmp_path / "does_not_exist"
    service = GitService(client=GitClient(repository_path=str(nonexistent)))

    with pytest.raises(GitRepositoryNotFoundError):
        service.get_recent_commits()

    # Test via API mapping
    app.dependency_overrides[get_git_service] = lambda: service
    try:
        resp = client.get("/git/commits")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Configured Git repository is unavailable."
    finally:
        app.dependency_overrides.pop(get_git_service, None)


def test_repository_validation_non_git_directory(tmp_path: Path):
    """Existing directory that is not a Git repo raises GitRepositoryInvalidError and API returns 500."""
    non_git_dir = tmp_path / "plain_dir"
    non_git_dir.mkdir()
    service = GitService(client=GitClient(repository_path=str(non_git_dir)))

    with pytest.raises(GitRepositoryInvalidError):
        service.get_recent_commits()

    # Test via API mapping
    app.dependency_overrides[get_git_service] = lambda: service
    try:
        resp = client.get("/git/commits")
        assert resp.status_code == 500
        assert resp.json()["detail"] == "Configured path is not a valid Git repository."
    finally:
        app.dependency_overrides.pop(get_git_service, None)


# =====================================================================
# API Integration Tests: Commits Listing & Root Commits
# =====================================================================


def test_get_recent_commits(override_git_service):
    """GET /git/commits returns commits newest first with logical repository name."""
    _, hashes, _ = override_git_service

    resp = client.get("/git/commits?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["repository"] == "sentinelops-test"
    commits = data["commits"]
    assert len(commits) == 5

    # Newest first
    assert commits[0]["commit_hash"] == hashes["c5"]
    assert commits[0]["message"] == "Delete renamed module"
    assert commits[4]["commit_hash"] == hashes["c1"]
    assert commits[4]["message"] == "Add order service"

    # Test limit parameter
    resp_limit = client.get("/git/commits?limit=2")
    assert resp_limit.status_code == 200
    assert len(resp_limit.json()["commits"]) == 2


def test_get_recent_commits_limit_validation():
    """Limit parameter outside 1..50 must fail validation with 422."""
    resp1 = client.get("/git/commits?limit=0")
    assert resp1.status_code == 422

    resp2 = client.get("/git/commits?limit=51")
    assert resp2.status_code == 422


def test_root_commit_details_and_diff(override_git_service):
    """Root commit (Commit 1) has no parent, but details and diff must work seamlessly."""
    _, hashes, _ = override_git_service
    c1 = hashes["c1"]

    # 1. Commit details
    resp_details = client.get(f"/git/commits/{c1}")
    assert resp_details.status_code == 200
    details = resp_details.json()
    assert details["commit"]["commit_hash"] == c1
    assert details["commit"]["message"] == "Add order service"
    assert len(details["changed_files"]) == 1

    changed = details["changed_files"][0]
    assert changed["file_path"] == "demo_app/services/order_service.py"
    assert changed["change_type"] == "added"
    assert changed["additions"] == 3
    assert changed["deletions"] == 0

    # 2. Commit diff
    resp_diff = client.get(f"/git/commits/{c1}/diff")
    assert resp_diff.status_code == 200
    diff_data = resp_diff.json()
    assert diff_data["commit_hash"] == c1
    assert diff_data["truncated"] is False
    assert "+++ b/demo_app/services/order_service.py" in diff_data["diff"]
    assert "+class OrderService:" in diff_data["diff"]


def test_commit_details_modified_file(override_git_service):
    """Commit 2 details should report modified file with additions and deletions."""
    _, hashes, _ = override_git_service
    c2 = hashes["c2"]

    resp = client.get(f"/git/commits/{c2}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["commit"]["commit_hash"] == c2
    assert len(data["changed_files"]) == 1
    changed = data["changed_files"][0]
    assert changed["file_path"] == "demo_app/services/order_service.py"
    assert changed["change_type"] == "modified"
    assert changed["additions"] is not None
    assert changed["deletions"] is not None


def test_commit_diff_filtered_by_path(override_git_service):
    """Diff filtered by path returns only changes for that specific file."""
    _, hashes, _ = override_git_service
    c2 = hashes["c2"]

    # Path that exists in commit
    resp = client.get(f"/git/commits/{c2}/diff?path=demo_app/services/order_service.py")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_path"] == "demo_app/services/order_service.py"
    assert "raise OrderProcessingError" in data["diff"]

    # Path that did NOT change in commit 2
    resp_empty = client.get(f"/git/commits/{c2}/diff?path=nonexistent_file.py")
    assert resp_empty.status_code == 200
    assert resp_empty.json()["diff"].strip() == ""


def test_commit_rename_detection(override_git_service):
    """Commit 4 (rename) must report change_type='renamed' with both old_path and file_path."""
    _, hashes, _ = override_git_service
    c4 = hashes["c4"]

    resp = client.get(f"/git/commits/{c4}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["changed_files"]) == 1
    changed = data["changed_files"][0]
    assert changed["change_type"] == "renamed"
    assert changed["old_path"] == "demo_app/services/unrelated.py"
    assert changed["file_path"] == "demo_app/services/renamed.py"


def test_deleted_file_history(override_git_service):
    """File history for a deleted file must succeed even though file no longer exists in working tree."""
    _, hashes, _ = override_git_service

    resp = client.get("/git/files/history?path=demo_app/services/renamed.py")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_path"] == "demo_app/services/renamed.py"
    commits = data["commits"]
    assert len(commits) >= 1
    # Commit 5 was the deletion commit
    commit_hashes = [c["commit_hash"] for c in commits]
    assert hashes["c5"] in commit_hashes


def test_file_history_filtering(override_git_service):
    """File history for order_service.py must include Commit 1 and 2, but omit unrelated commits."""
    _, hashes, _ = override_git_service

    resp = client.get("/git/files/history?path=demo_app/services/order_service.py&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_path"] == "demo_app/services/order_service.py"
    commits = data["commits"]
    found_hashes = [c["commit_hash"] for c in commits]

    # Must contain c1 and c2
    assert hashes["c1"] in found_hashes
    assert hashes["c2"] in found_hashes

    # Must NOT contain unrelated c3
    assert hashes["c3"] not in found_hashes


def test_unknown_commit_hash_returns_404(override_git_service):
    """Valid-looking hexadecimal commit hash that does not exist returns HTTP 404."""
    unknown_hash = "abcdef0123456789abcdef0123456789abcdef01"
    resp = client.get(f"/git/commits/{unknown_hash}")
    assert resp.status_code == 404
    assert f"Commit '{unknown_hash}' not found" in resp.json()["detail"]


def test_invalid_commit_format_rejected(override_git_service):
    """Arbitrary Git revisions and malformed hashes must be rejected with 400 before Git executes."""
    # Symbolic revisions
    assert client.get("/git/commits/HEAD~1").status_code == 400
    assert client.get("/git/commits/main").status_code == 400
    assert client.get("/git/commits/HEAD").status_code == 400

    # Path traversal / command injection attempts
    assert client.get("/git/commits/invalid..hash").status_code == 400
    assert client.get("/git/commits/abc;rm").status_code == 400

    # Too short (< 7 chars)
    assert client.get("/git/commits/abc12").status_code == 400


def test_path_traversal_rejected(override_git_service):
    """Directory traversal and absolute paths must be rejected with HTTP 400."""
    assert client.get("/git/files/history?path=../../secret.txt").status_code == 400
    assert client.get("/git/files/history?path=..\\..\\secret.txt").status_code == 400
    assert client.get("/git/files/history?path=/etc/passwd").status_code == 400
    assert client.get("/git/files/history?path=C:\\Windows\\system.ini").status_code == 400


def test_posix_paths_always_returned(override_git_service):
    """All file paths returned by API must strictly use forward slashes."""
    _, hashes, _ = override_git_service
    resp = client.get(f"/git/commits/{hashes['c1']}")
    assert resp.status_code == 200
    for f in resp.json()["changed_files"]:
        assert "\\" not in f["file_path"]
        if f["old_path"]:
            assert "\\" not in f["old_path"]


def test_diff_truncation(override_git_service):
    """Diffs exceeding max_chars must return truncated=True and bounded diff text."""
    _, hashes, service = override_git_service
    c1 = hashes["c1"]

    # Request diff with artificially small max_chars
    diff_res = service.get_commit_diff(commit_hash=c1, max_chars=30)
    assert diff_res.truncated is True
    assert len(diff_res.diff) <= 30


def test_timezone_aware_timestamps(override_git_service):
    """Author and committer timestamps parsed from Git must be timezone-aware."""
    _, hashes, service = override_git_service
    meta = service.get_commit_details(hashes["c1"]).commit
    assert meta.authored_at.tzinfo is not None
    assert meta.committed_at.tzinfo is not None
