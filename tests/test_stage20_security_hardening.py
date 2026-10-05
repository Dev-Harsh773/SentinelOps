"""Stage 20 security and hardening unit and integration tests."""

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.common.config import config
from app.common.security import (
    GitArgumentSecurityError,
    GitArgumentValidator,
    PathJail,
    PathTraversalSecurityError,
    SSRFGuard,
    SSRFValidationError,
)
from app.main import create_app
from app.repository.models import GitFilePathInvalidError
from app.repository.service import GitService, validate_commit_reference, validate_git_path
from app.retrieval.scanner import SourceScanner


# -----------------------------------------------------------------------------
# SSRFGuard Tests
# -----------------------------------------------------------------------------

def test_ssrf_rejects_cloud_metadata_across_all_environments():
    """Assert 169.254.169.254 and metadata hostnames are blocked in dev and prod."""
    for env in ("development", "production", "test"):
        with pytest.raises(SSRFValidationError, match="forbidden"):
            SSRFGuard.validate_url("http://169.254.169.254/latest/meta-data", app_env=env)

        with pytest.raises(SSRFValidationError, match="forbidden"):
            SSRFGuard.validate_url("http://metadata.google.internal/computeMetadata/v1", app_env=env)


def test_ssrf_production_rejects_rfc1918_private_ranges():
    """Assert RFC 1918 private subnets and loopback are rejected in production."""
    with pytest.raises(SSRFValidationError, match="Private network target|forbidden in production"):
        SSRFGuard.validate_url("http://192.168.1.1/api", app_env="production")

    with pytest.raises(SSRFValidationError, match="Private network target|forbidden in production"):
        SSRFGuard.validate_url("http://10.0.0.1/api", app_env="production")

    with pytest.raises(SSRFValidationError, match="Loopback target|forbidden in production"):
        SSRFGuard.validate_url("http://127.0.0.1:8000/health", app_env="production")


def test_ssrf_production_unpacks_and_blocks_ipv4_mapped_ipv6():
    """Assert ::ffff:127.0.0.1 and ::ffff:169.254.169.254 are unwrapped and blocked."""
    with pytest.raises(SSRFValidationError):
        SSRFGuard.validate_url("http://[::ffff:169.254.169.254]/", app_env="production")

    with pytest.raises(SSRFValidationError):
        SSRFGuard.validate_url("http://[::ffff:127.0.0.1]/", app_env="production")


def test_ssrf_development_allows_localhost():
    """Assert localhost and 127.0.0.1 are permitted in development mode."""
    # Should not raise
    SSRFGuard.validate_url("http://127.0.0.1:8000/health", app_env="development")
    SSRFGuard.validate_url("http://localhost:8000/health", app_env="development")


def test_ssrf_multi_dns_answer_rejection(monkeypatch):
    """Assert if DNS returns multiple IPs including a forbidden IP, request is rejected."""
    import socket

    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    with pytest.raises(SSRFValidationError, match="cloud metadata"):
        SSRFGuard.validate_url("http://example.com/api", app_env="development")


# -----------------------------------------------------------------------------
# Git Argument & Subprocess Security Tests
# -----------------------------------------------------------------------------

def test_git_branch_validator_rejects_leading_dash():
    """Assert branch names starting with hyphens are rejected."""
    with pytest.raises(GitArgumentSecurityError, match="cannot start with a hyphen"):
        GitArgumentValidator.validate_branch_name("--orphan")

    with pytest.raises(GitArgumentSecurityError, match="cannot start with a hyphen"):
        GitArgumentValidator.validate_branch_name("-b")


def test_git_branch_validator_rejects_dangerous_characters():
    """Assert branch names with traversal or forbidden characters are rejected."""
    with pytest.raises(GitArgumentSecurityError, match="forbidden characters"):
        GitArgumentValidator.validate_branch_name("feature/../../escape")

    with pytest.raises(GitArgumentSecurityError, match="forbidden characters"):
        GitArgumentValidator.validate_branch_name("branch~1")


def test_git_commit_validator_rejects_options():
    """Assert commit hashes starting with hyphens or invalid characters are rejected."""
    with pytest.raises(GitArgumentSecurityError, match="cannot start with a hyphen"):
        GitArgumentValidator.validate_commit_hash("-m")

    with pytest.raises(GitArgumentSecurityError, match="Invalid commit hash format"):
        GitArgumentValidator.validate_commit_hash("not-a-hex-sha")

    # Valid hex passes
    valid_sha = "a" * 40
    assert GitArgumentValidator.validate_commit_hash(valid_sha) == valid_sha


def test_git_checkout_command_construction(monkeypatch):
    """Verifies create_and_checkout_branch runs git checkout -b <branch> <base_commit> without invalid --."""
    from app.repository.branch_manager import GitBranchManager

    executed_commands = []

    def mock_run_git(self, args):
        executed_commands.append(args)
        if "rev-parse" in args:
            return 0, "true", ""
        return 0, "", ""

    monkeypatch.setattr(GitBranchManager, "_run_git", mock_run_git)
    manager = GitBranchManager(repository_path=".")
    
    sha = "1234567890abcdef1234567890abcdef12345678"
    manager.create_and_checkout_branch("remediation/fix-123", sha)

    assert any(cmd == ["checkout", "-b", "remediation/fix-123", sha] for cmd in executed_commands)


def test_git_path_separator_uses_double_dash(monkeypatch):
    """Verifies diff-tree and log commands insert -- before repository file pathspecs and reject traversal."""
    from app.repository.client import GitClient

    executed_commands = []

    def mock_run_git(self, args):
        executed_commands.append(args)
        return 0, "", ""

    monkeypatch.setattr(GitClient, "_run_git", mock_run_git)
    client = GitClient(repository_path=".")

    sha = "1234567890abcdef1234567890abcdef12345678"
    client.get_commit_diff(commit_hash=sha, path="app/main.py")
    assert any("--" in cmd and "app/main.py" in cmd for cmd in executed_commands)

    client.get_file_history(path="app/main.py", limit=5)
    assert any("--" in cmd and "app/main.py" in cmd for cmd in executed_commands)

    # Traversal rejection in GitClient
    with pytest.raises(GitFilePathInvalidError, match="Directory traversal"):
        client.get_commit_diff(commit_hash=sha, path="../outside.py")

    with pytest.raises(GitFilePathInvalidError, match="Directory traversal"):
        client.get_file_history(path="../outside.py", limit=5)


# -----------------------------------------------------------------------------
# PathJail & Filesystem Boundary Tests
# -----------------------------------------------------------------------------

def test_path_jail_rejects_boundary_escape(tmp_path):
    """Assert PathJail rejects paths resolving outside workspace root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(PathTraversalSecurityError, match="escapes workspace boundary"):
        PathJail.ensure_within_workspace(workspace, "../secret.txt")

    # Valid internal path succeeds
    safe_target = workspace / "sub" / "code.py"
    safe_target.parent.mkdir()
    safe_target.write_text("print(1)")
    resolved = PathJail.ensure_within_workspace(workspace, "sub/code.py")
    assert resolved == safe_target.resolve()


def test_path_jail_excludes_escaping_symlinks(tmp_path):
    """Assert directory symlinks resolving outside the project root are ignored by SourceScanner."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "secret.py"
    outside_file.write_text("SECRET = 1")

    # Create inside file
    inside_file = workspace / "inside.py"
    inside_file.write_text("INSIDE = 1")

    # Create directory symlink pointing outside
    symlink_dir = workspace / "linked_outside"
    try:
        symlink_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted in this test environment")

    scanner = SourceScanner()
    discovered = scanner.scan(workspace)
    discovered_rel_paths = [p[0] for p in discovered]

    # Inside file is indexed
    assert any("inside.py" in p for p in discovered_rel_paths)
    # Outside file via directory symlink is pruned and excluded
    assert not any("secret.py" in p for p in discovered_rel_paths)


def test_path_jail_excludes_escaping_file_symlink(tmp_path):
    """Assert file symlinks resolving outside the project root are ignored by SourceScanner."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "outside_target.py"
    outside_file.write_text("OUTSIDE_VAL = 999")

    # Normal inside file
    inside_file = workspace / "normal_inside.py"
    inside_file.write_text("INSIDE_VAL = 111")

    # File symlink inside workspace pointing to outside target
    escaping_file_symlink = workspace / "escaping_link.py"
    try:
        escaping_file_symlink.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("File symlink creation not permitted in this test environment")

    scanner = SourceScanner()
    discovered = scanner.scan(workspace)
    discovered_files = [p[0] for p in discovered]
    discovered_abs = [p[1] for p in discovered]

    # Normal file is indexed
    assert any("normal_inside.py" in f for f in discovered_files)
    # Escaping file symlink is NOT indexed or returned
    assert not any("escaping_link.py" in f for f in discovered_files)
    assert not any("outside_target.py" in str(p) for p in discovered_abs)


def test_path_jail_excludes_windows_directory_junction(tmp_path):
    """Assert Windows directory junctions resolving outside the project root are detected and pruned."""
    import sys
    import subprocess

    if sys.platform != "win32":
        pytest.skip("Directory junctions are specific to Windows")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside_junction_target"
    outside.mkdir()
    secret_in_outside = outside / "secret_junction_code.py"
    secret_in_outside.write_text("SECRET_JUNCTION = True")

    inside_file = workspace / "real_file.py"
    inside_file.write_text("REAL = True")

    junction_path = workspace / "junction_dir"

    # Create Windows directory junction using mklink /J
    cmd = ["cmd", "/c", "mklink", "/J", str(junction_path), str(outside)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        pytest.skip(f"mklink /J not permitted or failed: {res.stderr}")

    try:
        assert hasattr(junction_path, "is_junction") and junction_path.is_junction()
        scanner = SourceScanner()
        discovered = scanner.scan(workspace)
        discovered_rel_paths = [p[0] for p in discovered]

        # Normal file is indexed
        assert any("real_file.py" in p for p in discovered_rel_paths)
        # Secret in outside junction directory is pruned and excluded
        assert not any("secret_junction_code.py" in p for p in discovered_rel_paths)
    finally:
        # Cleanup junction
        if junction_path.exists():
            try:
                subprocess.run(["cmd", "/c", "rmdir", str(junction_path)], capture_output=True)
            except Exception:
                pass


def test_git_service_rejects_path_traversal():
    """Assert GitService.get_file_history rejects directory traversal with '..'."""
    with pytest.raises(GitFilePathInvalidError, match="Directory traversal"):
        validate_git_path("../outside.py")


# -----------------------------------------------------------------------------
# Middleware, HTTP Headers & Error Sanitization Tests
# -----------------------------------------------------------------------------

def test_security_headers_emitted():
    """Verify security headers are emitted on responses."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"


def test_hsts_not_emitted_on_plain_http():
    """Verify Strict-Transport-Security is not emitted for plain HTTP development requests."""
    app = create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert "Strict-Transport-Security" not in response.headers


def test_content_length_limit_exceeded():
    """Verify requests with Content-Length exceeding limit return 413."""
    app = create_app()
    client = TestClient(app)
    headers = {"Content-Length": "20000000"}  # 20MB > 10MB
    response = client.post("/health", headers=headers, content=b"x")
    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


def test_structured_sanitized_error_response():
    """Verify unhandled exceptions return structured JSON error with trace_id and zero local disk paths."""
    app = create_app()

    @app.get("/test-error-route")
    def error_route():
        raise RuntimeError("Secret internal failure in D:\\SentileOps\\secret\\db.py")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-error-route")
    assert response.status_code == 500
    data = response.json()
    assert data["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "trace_id" in data
    assert "D:\\SentileOps" not in response.text
    assert "Secret internal failure" not in response.text


def test_secret_scrubbing_in_delivery_failures():
    """Verify webhook failure scrubber cleans bearer tokens and passwords."""
    from app.connectors.redaction import scrub_string

    raw_error = "Connection failed for Bearer my_secret_token_123456789 and ghp_abcdefghijklmnopqrstuvwx"
    scrubbed = scrub_string(raw_error)
    assert "my_secret_token_123456789" not in scrubbed
    assert "ghp_abcdefghijklmnopqrstuvwx" not in scrubbed
    assert "[REDACTED" in scrubbed
