"""Low-level read-only Git subprocess client for SentinelOps."""

from datetime import datetime
from pathlib import Path
import re
import subprocess
from typing import Dict, List, Optional, Tuple

from app.repository.models import (
    ChangedFile,
    CommitDiff,
    GitCommandError,
    GitCommit,
    GitCommitNotFoundError,
    GitRepositoryInvalidError,
    GitRepositoryNotFoundError,
)

# Standard mapping from Git diff status letters to normalized change types
STATUS_MAP: Dict[str, str] = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "modified",  # type changed (e.g. regular file to symlink)
}

# Machine-readable log format:
# %H = commit hash, %h = short hash, %an = author name, %ae = author email
# %aI = author ISO-8601 date, %cI = committer ISO-8601 date, %B = raw message body
# Delimiters: \x1f (ASCII unit separator) between fields, \x1e (ASCII record separator) between commits
GIT_LOG_FORMAT = "%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%cI%x1f%B%x1e"


class GitClient:
    """Executes read-only Git commands using Python standard library subprocess."""

    def __init__(self, repository_path: str = ".", timeout_seconds: int = 10):
        self._repo_path = Path(repository_path).resolve()
        self._timeout = timeout_seconds

    @property
    def repository_path(self) -> Path:
        """Physical filesystem path of the repository."""
        return self._repo_path

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
        """Verifies that the configured path exists and is inside a valid Git working tree."""
        if not self._repo_path.exists() or not self._repo_path.is_dir():
            raise GitRepositoryNotFoundError()

        ret, stdout, stderr = self._run_git(["rev-parse", "--is-inside-work-tree"])
        if ret != 0 or stdout.strip() != "true":
            raise GitRepositoryInvalidError()

    def resolve_commit(self, commit_ref: str) -> str:
        """Resolves a valid commit reference (hex hash) to its full 40-character commit hash.

        Raises:
            GitCommitNotFoundError: If commit_ref does not exist or is not a commit object.
        """
        ret, stdout, _ = self._run_git(
            ["rev-parse", "--verify", "--quiet", f"{commit_ref}^{{commit}}"]
        )
        if ret != 0 or not stdout.strip():
            raise GitCommitNotFoundError(commit_ref)
        return stdout.strip()

    def get_recent_commits(self, limit: int = 10) -> List[GitCommit]:
        """Returns the most recent commits, newest first."""
        ret, stdout, stderr = self._run_git(
            ["log", f"--format={GIT_LOG_FORMAT}", f"-n{limit}"]
        )
        if ret != 0:
            raise GitCommandError(f"git log -n{limit}", ret, stderr)
        return self._parse_log_output(stdout)

    def get_commit_metadata(self, commit_hash: str) -> GitCommit:
        """Returns metadata for a specific resolved commit."""
        ret, stdout, stderr = self._run_git(
            ["log", "-1", f"--format={GIT_LOG_FORMAT}", commit_hash]
        )
        if ret != 0:
            raise GitCommandError(f"git log -1 {commit_hash}", ret, stderr)
        commits = self._parse_log_output(stdout)
        if not commits:
            raise GitCommitNotFoundError(commit_hash)
        return commits[0]

    def get_changed_files(self, commit_hash: str) -> List[ChangedFile]:
        """Retrieves changed files for a commit with status and addition/deletion counts."""
        # 1. Name-status with null delimiters (-z) and rename detection (-M)
        ret_ns, stdout_ns, stderr_ns = self._run_git(
            ["diff-tree", "--root", "-r", "--no-commit-id", "-z", "--name-status", "-M", commit_hash]
        )
        if ret_ns != 0:
            raise GitCommandError(f"git diff-tree --name-status {commit_hash}", ret_ns, stderr_ns)

        # 2. Numstat with null delimiters (-z) and rename detection (-M)
        ret_num, stdout_num, stderr_num = self._run_git(
            ["diff-tree", "--root", "-r", "--no-commit-id", "-z", "--numstat", "-M", commit_hash]
        )
        if ret_num != 0:
            raise GitCommandError(f"git diff-tree --numstat {commit_hash}", ret_num, stderr_num)

        numstat_map = self._parse_numstat_z(stdout_num)
        name_status_records = self._parse_name_status_z(stdout_ns)

        changed_files: List[ChangedFile] = []
        for raw_status, old_p, file_p in name_status_records:
            norm_file_path = file_p.replace("\\", "/")
            norm_old_path = old_p.replace("\\", "/") if old_p else None

            # Determine change type (e.g. R100 -> renamed, M -> modified, A -> added)
            status_char = raw_status[0].upper()
            change_type = STATUS_MAP.get(status_char, "modified")

            additions, deletions = numstat_map.get(norm_file_path, (None, None))

            changed_files.append(
                ChangedFile(
                    file_path=norm_file_path,
                    change_type=change_type,
                    old_path=norm_old_path,
                    additions=additions,
                    deletions=deletions,
                )
            )

        return changed_files

    def get_commit_diff(
        self,
        commit_hash: str,
        path: Optional[str] = None,
        max_chars: int = 50000,
    ) -> CommitDiff:
        """Returns the unified text diff for a commit or specific file, with bounded length."""
        cmd = ["diff-tree", "--root", "-p", "-M", "--no-commit-id", commit_hash]
        if path:
            cmd.extend(["--", path])

        ret, stdout, stderr = self._run_git(cmd)
        if ret != 0:
            raise GitCommandError(f"git diff-tree -p {commit_hash}", ret, stderr)

        raw_diff = stdout
        truncated = False
        if len(raw_diff) > max_chars:
            truncated = True
            diff_slice = raw_diff[:max_chars]
            # Try to break cleanly at the last newline within slice
            last_nl = diff_slice.rfind("\n")
            diff_text = diff_slice[:last_nl] if last_nl > 0 else diff_slice
        else:
            diff_text = raw_diff

        return CommitDiff(
            commit_hash=commit_hash,
            file_path=path,
            diff=diff_text,
            truncated=truncated,
        )

    def get_file_history(self, path: str, limit: int = 10) -> List[GitCommit]:
        """Returns commits that touched a specific file path, newest first."""
        ret, stdout, stderr = self._run_git(
            ["log", f"--format={GIT_LOG_FORMAT}", f"-n{limit}", "--", path]
        )
        if ret != 0:
            raise GitCommandError(f"git log -n{limit} -- {path}", ret, stderr)
        return self._parse_log_output(stdout)

    # -----------------------------------------------------------------
    # Private Parsers for Machine-Readable Formats
    # -----------------------------------------------------------------

    def _parse_log_output(self, raw_output: str) -> List[GitCommit]:
        """Parses machine-formatted git log output into a list of GitCommit objects."""
        if not raw_output:
            return []

        commits: List[GitCommit] = []
        raw_records = [r for r in raw_output.split("\x1e") if r.strip()]

        for record in raw_records:
            fields = record.strip("\r\n").split("\x1f")
            if len(fields) < 7:
                continue

            commit_h = fields[0].strip()
            short_h = fields[1].strip()
            author_n = fields[2].strip()
            author_e = fields[3].strip()
            authored_at = datetime.fromisoformat(fields[4].strip())
            committed_at = datetime.fromisoformat(fields[5].strip())
            msg = fields[6].strip()

            commits.append(
                GitCommit(
                    commit_hash=commit_h,
                    short_hash=short_h,
                    author_name=author_n,
                    author_email=author_e,
                    authored_at=authored_at,
                    committed_at=committed_at,
                    message=msg,
                )
            )

        return commits

    def _parse_name_status_z(self, raw_str: str) -> List[Tuple[str, Optional[str], str]]:
        """Parses null-terminated diff-tree --name-status output into (status, old_path, new_path)."""
        records: List[Tuple[str, Optional[str], str]] = []
        tokens = raw_str.split("\x00")
        i = 0
        while i < len(tokens):
            item = tokens[i]
            if not item:
                i += 1
                continue
            status_code = item
            if status_code.startswith(("R", "C")):
                if i + 2 < len(tokens):
                    old_path = tokens[i + 1]
                    new_path = tokens[i + 2]
                    records.append((status_code, old_path, new_path))
                    i += 3
                    continue
            else:
                if i + 1 < len(tokens):
                    file_path = tokens[i + 1]
                    records.append((status_code, None, file_path))
                    i += 2
                    continue
            i += 1
        return records

    def _parse_numstat_z(self, raw_str: str) -> Dict[str, Tuple[Optional[int], Optional[int]]]:
        """Parses null-terminated diff-tree --numstat output into a map of file_path -> (adds, dels)."""
        records: Dict[str, Tuple[Optional[int], Optional[int]]] = {}
        tokens = raw_str.split("\x00")
        i = 0
        while i < len(tokens):
            item = tokens[i]
            if not item:
                i += 1
                continue
            parts = item.split("\t")
            if len(parts) >= 3:
                add_s, del_s, path = parts[0], parts[1], parts[2]
                adds = int(add_s) if add_s != "-" else None
                dels = int(del_s) if del_s != "-" else None
                if not path:
                    # Rename record: old_path is tokens[i+1], new_path is tokens[i+2]
                    if i + 2 < len(tokens):
                        new_path = tokens[i + 2].replace("\\", "/")
                        records[new_path] = (adds, dels)
                        i += 3
                        continue
                else:
                    norm_p = path.replace("\\", "/")
                    records[norm_p] = (adds, dels)
            i += 1
        return records
