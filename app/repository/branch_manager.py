"""Git branch management operations for SentinelOps remediation branches."""

import logging
from pathlib import Path
import subprocess
from typing import List, Tuple

from app.repository.models import (
    GitCommandError,
    GitRepositoryInvalidError,
    GitRepositoryNotFoundError,
)

logger = logging.getLogger(__name__)


class GitBranchManager:
    """Manages safe, isolated Git branch creation and checkout operations for SentinelOps."""

    def __init__(
        self,
        repository_path: str = ".",
        base_branch: str = "main",
        timeout_seconds: int = 10,
    ) -> None:
        self._repo_path = Path(repository_path).resolve()
        self._base_branch = base_branch.strip()
        self._timeout = timeout_seconds

    @property
    def repository_path(self) -> Path:
        """Physical filesystem path of the target Git repository."""
        return self._repo_path

    @property
    def base_branch(self) -> str:
        """Configured trusted base branch."""
        return self._base_branch

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        """Executes a Git subprocess with shell=False, capturing output and enforcing timeout."""
        cmd = ["git", "-C", str(self._repo_path)] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                shell=False,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(
                command=" ".join(cmd),
                exit_code=-1,
                stderr=f"Git command timed out after {self._timeout}s",
            ) from exc
        except Exception as exc:
            raise GitCommandError(
                command=" ".join(cmd),
                exit_code=-1,
                stderr=str(exc),
            ) from exc

    def validate_repository(self) -> None:
        """Verifies that the target path exists and is inside a valid Git repository."""
        if not self._repo_path.exists() or not self._repo_path.is_dir():
            raise GitRepositoryNotFoundError()

        ret, stdout, _ = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if ret != 0 or stdout.strip() != "true":
            raise GitRepositoryInvalidError()

    def get_current_branch(self) -> str:
        """Returns the name of the currently checked out Git branch."""
        self.validate_repository()
        ret, stdout, stderr = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if ret != 0 or not stdout.strip():
            raise GitCommandError("git rev-parse --abbrev-ref HEAD", ret, stderr)
        return stdout.strip()

    def get_head_commit(self) -> str:
        """Returns the full 40-character hexadecimal SHA of current HEAD."""
        self.validate_repository()
        ret, stdout, stderr = self._run_git(["rev-parse", "HEAD"])
        if ret != 0 or not stdout.strip():
            raise GitCommandError("git rev-parse HEAD", ret, stderr)
        return stdout.strip()

    def check_working_tree_clean(self) -> bool:
        """Returns True if the working tree has no uncommitted changes in tracked files.

        Untracked files are ignored to allow test fixtures and environment files.
        """
        self.validate_repository()
        ret, stdout, stderr = self._run_git(["status", "--porcelain", "--untracked-files=no"])
        if ret != 0:
            raise GitCommandError("git status --porcelain --untracked-files=no", ret, stderr)
        # If output is non-empty, tracked files have unstaged or staged modifications
        return len(stdout.strip()) == 0

    def branch_exists(self, branch_name: str) -> bool:
        """Checks if a local Git branch with branch_name already exists."""
        self.validate_repository()
        ret, _, _ = self._run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"])
        return ret == 0

    def create_and_checkout_branch(self, branch_name: str, base_commit: str) -> None:
        """Creates an isolated Git branch rooted at base_commit and checks it out.

        Executes `git checkout -b <branch_name> <base_commit>` without force flags.
        """
        self.validate_repository()
        ret, _, stderr = self._run_git(["checkout", "-b", branch_name, base_commit])
        if ret != 0:
            raise GitCommandError(f"git checkout -b {branch_name} {base_commit}", ret, stderr)
        logger.info(
            "Created and checked out branch '%s' from base commit '%s' in '%s'",
            branch_name,
            base_commit,
            self._repo_path,
        )
