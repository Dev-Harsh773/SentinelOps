"""Packaging runner for building the standalone SentinelOps Windows Control Center executable."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def build_control_center() -> int:
    """Run PyInstaller with desktop/control_center.spec and verify output bundle."""
    repo_root = Path(__file__).parent.parent.resolve()
    spec_file = repo_root / "desktop" / "control_center.spec"
    dist_dir = repo_root / "dist" / "SentinelOpsControlCenter"

    print(f"Building SentinelOps Control Center from: {spec_file}")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(repo_root / "dist"),
        "--workpath",
        str(repo_root / "build"),
        str(spec_file),
    ]

    result = subprocess.run(cmd, cwd=str(repo_root))
    if result.returncode != 0:
        print(f"PyInstaller build failed with exit code: {result.returncode}", file=sys.stderr)
        return result.returncode

    exe_file = dist_dir / "SentinelOpsControlCenter.exe"
    if not exe_file.exists():
        print(f"Expected executable not found at: {exe_file}", file=sys.stderr)
        return 1

    print(f"Successfully packaged standalone Windows Control Center at: {dist_dir}")
    print(f"Executable: {exe_file}")
    return 0


if __name__ == "__main__":
    sys.exit(build_control_center())
