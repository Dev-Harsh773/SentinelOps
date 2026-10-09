"""Smoke tests verifying backend distribution packages (wheel & sdist) and Windows Control Center binary."""

from pathlib import Path
import subprocess
import tarfile
import zipfile
import pytest


def test_control_center_binary_exists_and_runs():
    """Verify that the packaged standalone executable runs with --help and exits 0."""
    repo_root = Path(__file__).parent.parent.resolve()
    exe_path = repo_root / "dist" / "SentinelOpsControlCenter" / "SentinelOpsControlCenter.exe"

    if not exe_path.exists():
        pytest.skip(f"Packaged executable not found at {exe_path}; run package_control_center.py first.")

    # 1. Execute with --help
    cmd = [str(exe_path), "--help"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

    assert result.returncode == 0, f"Expected returncode 0, got {result.returncode}. Stderr: {result.stderr}"
    assert "SentinelOps Windows Control Center" in result.stdout

    # 2. Assert distribution directory contains no sensitive database or environment secrets
    dist_dir = exe_path.parent
    dist_files = [str(p.name) for p in dist_dir.glob("**/*") if p.is_file()]

    assert not any(f.endswith(".db") for f in dist_files), "Found .db file inside packaged dist directory!"
    assert not any(f.startswith(".env") for f in dist_files), "Found .env file inside packaged dist directory!"
    assert not any(f.endswith(".jsonl") for f in dist_files), "Found .jsonl runtime file inside packaged dist directory!"
    assert not any("workspaces" in str(p).lower() for p in dist_dir.glob("**/*")), "Found workspace inside packaged dist directory!"


def test_distribution_packages_exclude_sensitive_and_test_files():
    """Verify built .whl and .tar.gz archives strictly exclude tests/, .env*, .db*, .jsonl, and workspaces/ files."""
    repo_root = Path(__file__).parent.parent.resolve()
    dist_dir = repo_root / "dist"

    wheel_files = list(dist_dir.glob("*.whl"))
    sdist_files = list(dist_dir.glob("*.tar.gz"))

    if not wheel_files or not sdist_files:
        pytest.skip("Distribution packages (.whl or .tar.gz) not found in dist/; run 'python -m build' first.")

    wheel_path = wheel_files[0]
    sdist_path = sdist_files[0]

    # 1. Check Wheel archive contents
    with zipfile.ZipFile(wheel_path, "r") as zf:
        wheel_names = zf.namelist()
        for name in wheel_names:
            normalized = name.replace("\\", "/").lower()
            assert not normalized.startswith("tests/"), f"Wheel contains test file: {name}"
            assert "/tests/" not in normalized, f"Wheel contains test file: {name}"
            assert "workspaces" not in normalized, f"Wheel contains workspace file: {name}"
            assert not Path(normalized).name.startswith(".env"), f"Wheel contains .env file: {name}"
            assert not normalized.endswith((".db", ".db-wal", ".db-shm")), f"Wheel contains database file: {name}"
            assert not normalized.endswith(".jsonl"), f"Wheel contains runtime JSONL file: {name}"

    # 2. Check sdist (tar.gz) archive contents
    with tarfile.open(sdist_path, "r:gz") as tf:
        sdist_names = tf.getnames()
        for name in sdist_names:
            normalized = name.replace("\\", "/").lower()
            # In sdist, paths are prefixed with package-version/ (e.g. sentinelops-0.20.0/...)
            parts = normalized.split("/")
            # Check if any path segment is 'tests'
            assert "tests" not in parts[1:], f"sdist contains tests directory: {name}"
            assert "android" not in parts[1:], f"sdist contains android directory: {name}"
            assert "workspaces" not in parts[1:], f"sdist contains workspaces directory: {name}"
            filename = Path(normalized).name
            assert not filename.startswith(".env"), f"sdist contains .env file: {name}"
            assert not filename.endswith((".db", ".db-wal", ".db-shm")), f"sdist contains database file: {name}"
            assert not filename.endswith(".jsonl"), f"sdist contains runtime JSONL file: {name}"
