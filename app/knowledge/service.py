"""Domain service for Project Knowledge Base indexing, lazy hydration, and scoped retrieval."""

import ast
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import threading
from typing import Dict, List, Optional, Tuple

from app.common.config import config
from app.knowledge.models import ConfigFileInfo, DetectedRoute, ProjectKnowledgeSnapshot
from app.projects.models import Project, ProjectStatus
from app.projects.storage import ProjectNotFoundError, SqliteProjectStore
from app.repository.client import GitClient
from app.repository.models import GitCommit
from app.repository.service import GitService
from app.retrieval.index import CodeIndex
from app.retrieval.models import CodeChunk
from app.retrieval.parser import ParseError, PythonAstParser
from app.retrieval.scanner import RepositoryNotFoundError, SourceScanner
from app.retrieval.schemas import SearchResponse, SearchResultItem

logger = logging.getLogger("sentinelops.knowledge.service")

COMMON_CONFIG_FILES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "config.py",
    ".env.example",
    "package.json",
    "Dockerfile",
}

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}


class ProjectNotReadyError(Exception):
    """Raised when knowledge operations are attempted on a project in ERROR state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProjectNotIndexedError(Exception):
    """Raised when search is attempted on a project that has not been indexed yet."""

    def __init__(self, message: str = "Project has not been indexed yet.") -> None:
        super().__init__(message)


class ProjectWorkspaceNotFoundError(Exception):
    """Raised when the project workspace directory is missing on disk."""

    def __init__(self, path: str) -> None:
        super().__init__(f"Project workspace path does not exist on disk: {path}")
        self.path = path


class ProjectReindexError(Exception):
    """Raised when an explicit reindex operation encounters a fatal error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ProjectKnowledgeService:
    """Orchestrates project-scoped AST indexing, route extraction, Git context, and search."""

    def __init__(
        self,
        project_store: SqliteProjectStore,
        scanner: Optional[SourceScanner] = None,
        parser: Optional[PythonAstParser] = None,
    ) -> None:
        self._project_store = project_store
        self._scanner = scanner or SourceScanner(
            max_files=config.project_max_files if hasattr(config, "project_max_files") else 500,
            max_file_size=(
                config.project_max_file_bytes if hasattr(config, "project_max_file_bytes") else 1_000_000
            ),
        )
        self._parser = parser or PythonAstParser()

        # In-memory project indices and snapshots (process-lifetime)
        self._project_indexes: Dict[str, CodeIndex] = {}
        self._project_snapshots: Dict[str, ProjectKnowledgeSnapshot] = {}
        self._project_git_services: Dict[str, GitService] = {}

        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_project_lock(self, project_id: str) -> threading.Lock:
        """Obtain or allocate a per-project synchronization lock."""
        with self._global_lock:
            if project_id not in self._locks:
                self._locks[project_id] = threading.Lock()
            return self._locks[project_id]

    def has_project(self, project_id: str) -> bool:
        """Returns True if the project exists in SQLite storage."""
        if not project_id:
            return False
        return self._project_store.get_project(project_id) is not None

    def get_project(self, project_id: str) -> Project:
        """Retrieve project definition or raise ProjectNotFoundError."""
        project = self._project_store.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)
        return project

    def _extract_routes_and_configs(
        self, workspace_path: str, discovered_files: List[Tuple[str, Path]]
    ) -> Tuple[List[DetectedRoute], List[ConfigFileInfo]]:
        """Inspect AST for HTTP route decorators and locate known config files."""
        routes: List[DetectedRoute] = []
        configs: List[ConfigFileInfo] = []
        repo_dir = Path(workspace_path).resolve()

        # Config detection in root and immediate subdirs
        try:
            for item in repo_dir.iterdir():
                if item.is_file() and item.name in COMMON_CONFIG_FILES:
                    try:
                        configs.append(
                            ConfigFileInfo(
                                file_name=item.name,
                                rel_path=item.relative_to(repo_dir).as_posix(),
                                size_bytes=item.stat().st_size,
                            )
                        )
                    except OSError:
                        pass
        except OSError:
            pass

        # Route detection from Python files
        for rel_posix_path, abs_path in discovered_files:
            try:
                source = abs_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source, filename=rel_posix_path)
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for decorator in node.decorator_list:
                        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                            attr_name = decorator.func.attr.upper()
                            if attr_name in HTTP_METHODS and decorator.args:
                                first_arg = decorator.args[0]
                                if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                                    routes.append(
                                        DetectedRoute(
                                            method=attr_name,
                                            path=first_arg.value,
                                            file_path=rel_posix_path,
                                            function_name=node.name,
                                            start_line=node.lineno,
                                        )
                                    )

        # Deterministic sorting
        routes.sort(key=lambda r: (r.path, r.method, r.file_path, r.start_line))
        configs.sort(key=lambda c: c.rel_path)
        return routes, configs

    def _detect_git_metadata(self, workspace_path: str, is_git: bool) -> Tuple[Optional[str], Optional[str]]:
        """Detect current HEAD hash and current branch name if workspace is Git-backed."""
        if not is_git:
            return None, None
        try:
            client = GitClient(repository_path=workspace_path, timeout_seconds=5)
            commits = client.get_recent_commits(limit=1)
            head_hash = commits[0].commit_hash if commits else None

            # Detect branch
            code, stdout, _ = client._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
            branch = stdout.strip() if code == 0 and stdout.strip() else "main"
            return head_hash, branch
        except Exception as exc:
            logger.debug("Failed detecting Git metadata for %s: %s", workspace_path, exc)
            return None, None

    def _compute_index_version(
        self,
        is_git: bool,
        current_head: Optional[str],
        chunks: List[CodeChunk],
        config_files: Optional[List[ConfigFileInfo]] = None,
        workspace_path: Optional[str] = None,
    ) -> str:
        """Generate a deterministic version identifier for the current index state.

        Includes:
        - Git HEAD identity (when Git-backed)
        - Deterministic indexed source content hash (sorted chunks with full content)
        - Deterministic discovered configuration file identity and content (sorted configs)
        """
        hasher = hashlib.sha256()

        # 1. Deterministic Python CodeChunks identity and content
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (c.file_path, c.start_line, c.end_line, c.symbol_name or ""),
        )
        for c in sorted_chunks:
            entry = f"chunk:{c.file_path}:{c.start_line}:{c.end_line}:{c.symbol_name or ''}:{c.content}\n"
            hasher.update(entry.encode("utf-8"))

        # 2. Deterministic discovered configuration manifests identity and content
        if config_files:
            sorted_configs = sorted(config_files, key=lambda cf: cf.rel_path)
            for cf in sorted_configs:
                config_content_hash = ""
                if workspace_path:
                    try:
                        p = Path(workspace_path) / cf.rel_path
                        if p.exists() and p.is_file():
                            config_content_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:8]
                    except Exception:
                        pass
                entry = f"config:{cf.rel_path}:{cf.file_name}:{cf.size_bytes}:{config_content_hash}\n"
                hasher.update(entry.encode("utf-8"))

        content_hash = hasher.hexdigest()[:8]

        if is_git and current_head:
            head_prefix = current_head[:8]
            return f"v1-{head_prefix}-{content_hash}"
        return f"v1-{content_hash}"

    def _scan_and_parse_workspace(
        self, project: Project
    ) -> Tuple[List[CodeChunk], List[DetectedRoute], List[ConfigFileInfo], int, int]:
        """Scan workspace and parse chunks, routes, and configs."""
        discovered = self._scanner.scan(project.workspace_path)
        all_chunks: List[CodeChunk] = []
        files_indexed = 0
        files_skipped = 0

        for rel_posix_path, abs_path in discovered:
            try:
                chunks = self._parser.parse_file(rel_posix_path, abs_path)
                all_chunks.extend(chunks)
                files_indexed += 1
            except ParseError as exc:
                logger.warning("Skipping unparseable file '%s': %s", rel_posix_path, exc)
                files_skipped += 1

        routes, configs = self._extract_routes_and_configs(project.workspace_path, discovered)
        return all_chunks, routes, configs, files_indexed, files_skipped

    def _get_or_hydrate_index(self, project_id: str) -> CodeIndex:
        """Return the in-memory CodeIndex, lazily hydrating from disk if absent (Issue 3)."""
        if project_id in self._project_indexes:
            return self._project_indexes[project_id]

        with self._get_project_lock(project_id):
            if project_id in self._project_indexes:
                return self._project_indexes[project_id]

            project = self.get_project(project_id)

            if project.status == ProjectStatus.ERROR:
                raise ProjectNotReadyError(
                    f"Project '{project_id}' is in ERROR state: {project.error_message}"
                )

            if project.status == ProjectStatus.REGISTERED:
                raise ProjectNotIndexedError(
                    f"Project '{project_id}' has not been indexed yet."
                )

            # status == ProjectStatus.READY -> Hydrate from disk
            ws_path = Path(project.workspace_path)
            if not ws_path.exists() or not ws_path.is_dir():
                project.status = ProjectStatus.ERROR
                project.error_message = (
                    f"Workspace directory missing after restart: {project.workspace_path}"
                )
                self._project_store.update_project(project)
                raise ProjectWorkspaceNotFoundError(project.workspace_path)

            now = datetime.now(timezone.utc)
            try:
                chunks, routes, configs, files_indexed, _ = self._scan_and_parse_workspace(project)
                head_sha, branch = self._detect_git_metadata(project.workspace_path, project.is_git)
                version = self._compute_index_version(
                    project.is_git, head_sha, chunks, configs, project.workspace_path
                )

                index = CodeIndex()
                index.rebuild(repository=project.name, chunks=chunks)
                self._project_indexes[project_id] = index

                snapshot = ProjectKnowledgeSnapshot(
                    project_id=project_id,
                    index_version=version,
                    indexed_at=now,
                    files_count=files_indexed,
                    chunks_count=len(chunks),
                    routes=routes,
                    config_files=configs,
                    is_git=project.is_git,
                    current_head=head_sha,
                    current_branch=branch,
                )
                self._project_snapshots[project_id] = snapshot

                # Synchronize SQLite so served knowledge and persisted metadata match exactly
                project.last_indexed_at = now
                project.index_version = version
                project.last_index_error = None
                self._project_store.update_project(project)

                logger.info("Successfully hydrated in-memory index for project '%s'", project_id)
                return index

            except Exception as exc:
                project.status = ProjectStatus.ERROR
                project.error_message = f"Restart hydration failed: {exc}"
                self._project_store.update_project(project)
                raise ProjectNotReadyError(str(exc)) from exc

    def index_project_initial(self, project_id: str) -> ProjectKnowledgeSnapshot:
        """Perform the initial build of a project's knowledge base upon registration."""
        project = self.get_project(project_id)
        with self._get_project_lock(project_id):
            now = datetime.now(timezone.utc)
            try:
                chunks, routes, configs, files_indexed, _ = self._scan_and_parse_workspace(project)
                head_sha, branch = self._detect_git_metadata(project.workspace_path, project.is_git)
                version = self._compute_index_version(
                    project.is_git, head_sha, chunks, configs, project.workspace_path
                )

                index = CodeIndex()
                index.rebuild(repository=project.name, chunks=chunks)
                self._project_indexes[project_id] = index

                snapshot = ProjectKnowledgeSnapshot(
                    project_id=project_id,
                    index_version=version,
                    indexed_at=now,
                    files_count=files_indexed,
                    chunks_count=len(chunks),
                    routes=routes,
                    config_files=configs,
                    is_git=project.is_git,
                    current_head=head_sha,
                    current_branch=branch,
                )
                self._project_snapshots[project_id] = snapshot

                project.status = ProjectStatus.READY
                project.last_indexed_at = now
                project.index_version = version
                project.error_message = None
                project.last_index_error = None
                self._project_store.update_project(project)
                return snapshot

            except Exception as exc:
                project.status = ProjectStatus.ERROR
                project.error_message = str(exc)
                self._project_store.update_project(project)
                raise

    def reindex_project(self, project_id: str) -> ProjectKnowledgeSnapshot:
        """Refresh knowledge base. If refresh fails on a READY project, preserves previous index (Issue 5)."""
        project = self.get_project(project_id)
        with self._get_project_lock(project_id):
            ws_path = Path(project.workspace_path)
            now = datetime.now(timezone.utc)

            # Fatal workspace failure check
            if not ws_path.exists() or not ws_path.is_dir():
                err_msg = f"Workspace directory missing or unreadable: {project.workspace_path}"
                if project.status == ProjectStatus.READY:
                    project.last_index_error = err_msg
                    self._project_store.update_project(project)
                    raise ProjectReindexError(err_msg)
                else:
                    project.status = ProjectStatus.ERROR
                    project.error_message = err_msg
                    self._project_store.update_project(project)
                    raise ProjectWorkspaceNotFoundError(project.workspace_path)

            try:
                chunks, routes, configs, files_indexed, _ = self._scan_and_parse_workspace(project)
                head_sha, branch = self._detect_git_metadata(project.workspace_path, project.is_git)
                version = self._compute_index_version(
                    project.is_git, head_sha, chunks, configs, project.workspace_path
                )

                # Successful rebuild: atomic in-memory replacement
                active_index = self._project_indexes.get(project_id) or CodeIndex()
                active_index.rebuild(repository=project.name, chunks=chunks)
                self._project_indexes[project_id] = active_index

                snapshot = ProjectKnowledgeSnapshot(
                    project_id=project_id,
                    index_version=version,
                    indexed_at=now,
                    files_count=files_indexed,
                    chunks_count=len(chunks),
                    routes=routes,
                    config_files=configs,
                    is_git=project.is_git,
                    current_head=head_sha,
                    current_branch=branch,
                )
                self._project_snapshots[project_id] = snapshot

                # Clear previous refresh errors and advance version
                project.status = ProjectStatus.READY
                project.last_indexed_at = now
                project.index_version = version
                project.last_index_error = None
                self._project_store.update_project(project)
                return snapshot

            except Exception as exc:
                err_msg = f"Reindex failed: {exc}"
                if project.status == ProjectStatus.READY:
                    # Preserve previous good index, record error
                    project.last_index_error = err_msg
                    self._project_store.update_project(project)
                    raise ProjectReindexError(err_msg) from exc
                else:
                    project.status = ProjectStatus.ERROR
                    project.error_message = err_msg
                    self._project_store.update_project(project)
                    raise

    def get_project_knowledge(self, project_id: str) -> ProjectKnowledgeSnapshot:
        """Return knowledge snapshot, hydrating if necessary."""
        self._get_or_hydrate_index(project_id)
        return self._project_snapshots[project_id]

    def search_code(self, project_id: str, query: str, limit: int = 5) -> SearchResponse:
        """Execute lexical code search scoped to the project's CodeIndex."""
        index = self._get_or_hydrate_index(project_id)
        scored_chunks = index.search(query=query, limit=limit)
        results = [
            SearchResultItem(
                id=sc.chunk.id,
                file_path=sc.chunk.file_path,
                symbol_name=sc.chunk.symbol_name,
                symbol_type=sc.chunk.symbol_type,
                start_line=sc.chunk.start_line,
                end_line=sc.chunk.end_line,
                content=sc.chunk.content,
                score=sc.score,
            )
            for sc in scored_chunks
        ]
        return SearchResponse(query=query, total=len(results), results=results)

    def find_chunks_for_endpoint(self, project_id: str, endpoint: str) -> List[CodeChunk]:
        """Find AST chunks associated with an HTTP endpoint."""
        index = self._get_or_hydrate_index(project_id)
        snapshot = self._project_snapshots.get(project_id)
        if not snapshot:
            return []

        clean_ep = endpoint.strip()
        matching_routes = [r for r in snapshot.routes if r.path == clean_ep]
        chunks: List[CodeChunk] = []

        if matching_routes:
            with index._lock:
                for r in matching_routes:
                    for ch in index._chunks:
                        if ch.file_path == r.file_path and ch.start_line <= r.start_line <= ch.end_line:
                            if ch not in chunks:
                                chunks.append(ch)

        # Fallback to lexical query if not directly discovered in routes
        if not chunks:
            search_res = index.search(query=clean_ep, limit=3)
            chunks = [sc.chunk for sc in search_res]

        return chunks

    def get_git_service(self, project_id: str) -> Optional[GitService]:
        """Provide a project-scoped GitService if project is Git-backed."""
        project = self.get_project(project_id)
        if not project.is_git:
            return None

        with self._get_project_lock(project_id):
            if project_id not in self._project_git_services:
                client = GitClient(repository_path=project.workspace_path)
                self._project_git_services[project_id] = GitService(
                    client=client, repository_name=project.name
                )
            return self._project_git_services[project_id]

    def get_git_history_for_file(
        self, project_id: str, file_path: str, limit: int = 3
    ) -> List[GitCommit]:
        """Return Git commits touching a file in the project's workspace."""
        git_svc = self.get_git_service(project_id)
        if not git_svc:
            return []
        try:
            _, commits = git_svc.get_file_history(path=file_path, limit=limit)
            return commits
        except Exception as exc:
            logger.debug("Failed getting file history for %s in %s: %s", file_path, project_id, exc)
            return []

    def clear(self) -> None:
        """Clear all in-memory indices and caches. Strictly reserved for test isolation."""
        with self._global_lock:
            self._project_indexes.clear()
            self._project_snapshots.clear()
            self._project_git_services.clear()
            self._locks.clear()
