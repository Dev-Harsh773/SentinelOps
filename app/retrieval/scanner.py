"""Source-code filesystem scanner for repository indexing in SentinelOps."""

from pathlib import Path
from typing import List, Tuple

# Default directory names to ignore during scanning
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    "tests",
    "runtime",
    "venv",
    ".venv",
    "env",
    ".env",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
    "dist",
    "build",
    "node_modules",
    ".idea",
    ".vscode",
    "logs",
    ".tox",
    "coverage",
}


class RepositoryNotFoundError(Exception):
    """Raised when the specified repository path does not exist or is not a directory."""

    def __init__(self, path: str):
        super().__init__(f"Repository path does not exist or is not a directory: {path}")
        self.path = path


class SourceScanner:
    """Scans a repository filesystem tree for indexable source code files."""

    def __init__(
        self,
        excluded_dirs: set[str] | None = None,
        max_files: int | None = None,
        max_file_size: int | None = None,
    ):
        self._excluded_dirs = (
            {d.lower() for d in excluded_dirs} if excluded_dirs is not None else EXCLUDED_DIR_NAMES
        )
        self._max_files = max_files
        self._max_file_size = max_file_size

    def scan(self, repository_path: str | Path) -> List[Tuple[str, Path]]:
        """Recursively scans repository_path for Python (.py) files.

        Returns:
            A deterministically sorted list of (relative_posix_path, absolute_path) tuples.
        """
        repo_dir = Path(repository_path).resolve()
        if not repo_dir.exists() or not repo_dir.is_dir():
            raise RepositoryNotFoundError(str(repository_path))

        repo_name = repo_dir.name
        discovered: List[Tuple[str, Path]] = []

        for root_path, dirs, files in os_walk_filtered(repo_dir, self._excluded_dirs):
            for file_name in files:
                if not file_name.endswith(".py"):
                    continue

                candidate_file = root_path / file_name

                # Boundary safety: inspect candidate BEFORE resolution; skip symlinks/junctions escaping repo_dir
                from app.common.security import PathJail
                if not PathJail.is_safe_symlink_or_junction(repo_dir, candidate_file):
                    continue

                abs_file = candidate_file.resolve()

                # Boundary safety: verify resolved target is strictly within repo_dir
                try:
                    abs_file.relative_to(repo_dir)
                except ValueError:
                    continue

                # File size limit
                if self._max_file_size is not None:
                    try:
                        if abs_file.stat().st_size > self._max_file_size:
                            continue
                    except OSError:
                        continue

                try:
                    rel_to_repo = abs_file.relative_to(repo_dir).as_posix()
                except ValueError:
                    continue

                # Format relative path with logical repository root: e.g. demo_app/services/order_service.py
                rel_posix_path = f"{repo_name}/{rel_to_repo}" if rel_to_repo != "." else repo_name
                discovered.append((rel_posix_path, abs_file))

        # Deterministic ordering by relative POSIX path BEFORE applying file limit cap
        discovered.sort(key=lambda item: item[0])
        if self._max_files is not None and len(discovered) > self._max_files:
            discovered = discovered[: self._max_files]

        return discovered


def os_walk_filtered(base_dir: Path, excluded_dirs: set[str]):
    """Generator walking directory tree while pruning excluded directories and external symlinks."""
    import os
    from app.common.security import PathJail

    for root, dirs, files in os.walk(base_dir):
        # Prune excluded directories and directory symlinks/junctions pointing outside base_dir
        pruned_dirs = []
        for d in dirs:
            if d.lower() in excluded_dirs:
                continue
            dir_path = Path(root) / d
            # Inspect candidate directory before walking into it
            if not PathJail.is_safe_symlink_or_junction(base_dir, dir_path):
                continue
            pruned_dirs.append(d)

        dirs[:] = pruned_dirs
        yield Path(root), dirs, files
