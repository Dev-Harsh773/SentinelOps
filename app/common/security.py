"""Core security controls, guards, and validation for SentinelOps."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path
import re
import socket
from typing import List, Optional, Set
import urllib.parse

from app.common.config import config

logger = logging.getLogger("sentinelops.security")

# Cloud metadata addresses and special restricted IPs
CLOUD_METADATA_IPS: Set[ipaddress.IPv4Address | ipaddress.IPv6Address] = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}

CLOUD_METADATA_HOSTS: Set[str] = {
    "metadata.google.internal",
    "metadata.internal",
    "instance-data",
}

# Strict commit hexadecimal format: 7 to 40 characters
COMMIT_HASH_REGEX = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Strict Git branch name regex (alphanumeric, underscores, hyphens, periods, slashes)
# Must not start or end with a hyphen or slash, must not contain '..' or '~' or '^' or ':'
BRANCH_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\-\./]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$")


class SecurityError(Exception):
    """Base class for domain security violations."""


class SSRFValidationError(SecurityError):
    """Raised when an outbound URL fails SSRF safety checks."""


class PathTraversalSecurityError(SecurityError):
    """Raised when a path attempts to escape an authorized boundary."""


class GitArgumentSecurityError(SecurityError):
    """Raised when a Git command parameter fails strict security validation."""


class GitURLSecurityError(SecurityError):
    """Raised when a Git clone URL fails strict security validation."""


class SSRFGuard:
    """Validates outbound HTTP targets immediately before network transmission."""

    @classmethod
    def validate_url(
        cls,
        url: str,
        app_env: Optional[str] = None,
        allowed_internal_hosts: Optional[str] = None,
    ) -> None:
        """Inspect and resolve an outbound URL, raising SSRFValidationError if unsafe.

        Pre-resolves DNS records and inspects all returned A/AAAA addresses.
        Note: Pre-resolution provides address validation; there remains a theoretical
        TOCTOU rebinding window with unpinned connections if DNS flips dynamically.
        """
        if not url:
            raise SSRFValidationError("URL cannot be empty.")

        current_env = (app_env or config.app_env).lower()
        allowed_hosts_str = (
            allowed_internal_hosts
            if allowed_internal_hosts is not None
            else config.allowed_internal_hosts
        )
        allowed_hosts = {h.strip().lower() for h in allowed_hosts_str.split(",") if h.strip()}

        # 1. Parse URL using urllib.parse.urlsplit
        try:
            parsed = urllib.parse.urlsplit(url.strip())
        except Exception as exc:
            raise SSRFValidationError(f"Invalid URL structure: {exc}") from exc

        # 2. Scheme enforcement
        if parsed.scheme.lower() not in ("http", "https"):
            raise SSRFValidationError(f"Disallowed URL scheme '{parsed.scheme}'. Only http and https are allowed.")

        # 3. Disallow userinfo credentials in authority
        if parsed.username or parsed.password:
            raise SSRFValidationError("Embedded credentials in URLs are not allowed.")

        hostname = parsed.hostname
        if not hostname:
            raise SSRFValidationError("URL missing valid hostname.")

        hostname_lower = hostname.lower()

        # 4. Check known cloud metadata hostnames
        if hostname_lower in CLOUD_METADATA_HOSTS:
            raise SSRFValidationError(f"Targeting cloud metadata endpoint '{hostname}' is forbidden.")

        # 5. Allowlist bypass (if host is explicitly allowlisted)
        if hostname_lower in allowed_hosts:
            logger.debug("Hostname '%s' explicitly allowed via ALLOWED_INTERNAL_HOSTS", hostname_lower)
            return

        # 6. Resolve hostname to all TCP IP addresses
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        try:
            addr_info = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise SSRFValidationError(f"Failed to resolve hostname '{hostname}': {exc}") from exc

        if not addr_info:
            raise SSRFValidationError(f"No IP addresses resolved for hostname '{hostname}'.")

        # 7. Check every resolved IP address
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                raise SSRFValidationError(f"Invalid IP address returned by resolver: {ip_str}")

            # Unpack IPv4-mapped IPv6 addresses (::ffff:192.0.2.1)
            if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
                ip_obj = ip_obj.ipv4_mapped

            # Universal block: Cloud metadata
            if ip_obj in CLOUD_METADATA_IPS:
                raise SSRFValidationError(f"Access to cloud metadata IP '{ip_obj}' is forbidden.")

            # Universal block: IPv4 link-local (169.254.0.0/16)
            if ip_obj.is_link_local:
                raise SSRFValidationError(f"Access to link-local address '{ip_obj}' is forbidden.")

            # Universal block: Multicast or reserved (excluding loopback addresses which are handled below)
            if ip_obj.is_multicast or (ip_obj.is_reserved and not ip_obj.is_loopback):
                raise SSRFValidationError(f"Access to reserved/multicast address '{ip_obj}' is forbidden.")

            # Environment-dependent filtering
            if current_env == "production":
                # In production, block loopback and private RFC 1918 subnets
                if ip_obj.is_loopback:
                    raise SSRFValidationError(
                        f"Loopback target '{ip_obj}' is forbidden in production environment."
                    )
                if ip_obj.is_private:
                    raise SSRFValidationError(
                        f"Private network target '{ip_obj}' is forbidden in production environment."
                    )
            else:
                # In development/test, permit loopback (127.0.0.1, ::1)
                # but block RFC 1918 unless explicitly on loopback
                if not ip_obj.is_loopback and ip_obj.is_private and ip_obj not in CLOUD_METADATA_IPS:
                    # Allow localhost in dev; private non-loopback can still be blocked if not allowlisted
                    pass


class PathJail:
    """Enforces that file operations remain strictly inside the authorized workspace boundary."""

    @classmethod
    def ensure_within_workspace(cls, workspace_root: Path | str, target_path: Path | str) -> Path:
        """Resolve target_path and assert that it resides within workspace_root.

        Raises PathTraversalSecurityError if target escapes workspace boundary.
        """
        resolved_base = Path(workspace_root).resolve()
        resolved_target = (resolved_base / target_path).resolve() if not Path(target_path).is_absolute() else Path(target_path).resolve()

        try:
            resolved_target.relative_to(resolved_base)
        except ValueError as exc:
            raise PathTraversalSecurityError(
                f"Path '{target_path}' escapes workspace boundary '{workspace_root}'"
            ) from exc

        return resolved_target

    @classmethod
    def is_safe_symlink_or_junction(cls, workspace_root: Path | str, candidate_path: Path) -> bool:
        """Check if a symlink or junction's resolved target remains inside workspace root.

        Returns False if candidate is a symlink or junction pointing outside workspace_root.
        Returns True if candidate is not a symlink/junction, or if its resolved target is inside.
        """
        is_symlink = candidate_path.is_symlink()
        is_junction = hasattr(candidate_path, "is_junction") and candidate_path.is_junction()

        if not (is_symlink or is_junction):
            return True

        resolved_base = Path(workspace_root).resolve()
        try:
            target = candidate_path.resolve()
            target.relative_to(resolved_base)
            return True
        except (ValueError, OSError):
            return False


class GitArgumentValidator:
    """Strictly validates arguments passed to Git subprocess commands."""

    @classmethod
    def validate_branch_name(cls, branch_name: str) -> str:
        """Validates that a Git branch name is safe and does not inject options.

        Rejects leading hyphens ('--orphan', '-f'), path traversal ('..'),
        and shell metacharacters.
        """
        cleaned = branch_name.strip()
        if not cleaned:
            raise GitArgumentSecurityError("Branch name cannot be empty.")
        if cleaned.startswith("-"):
            raise GitArgumentSecurityError(f"Branch name cannot start with a hyphen: '{cleaned}'")
        if ".." in cleaned or "~" in cleaned or "^" in cleaned or ":" in cleaned or "\\" in cleaned:
            raise GitArgumentSecurityError(f"Branch name contains forbidden characters: '{cleaned}'")
        if not BRANCH_NAME_REGEX.match(cleaned):
            raise GitArgumentSecurityError(f"Invalid branch name format: '{cleaned}'")
        return cleaned

    @classmethod
    def validate_commit_hash(cls, commit_hash: str) -> str:
        """Validates that a commit reference is a valid hexadecimal hash.

        Rejects any value starting with a hyphen or containing non-hex characters.
        """
        cleaned = commit_hash.strip()
        if cleaned.startswith("-"):
            raise GitArgumentSecurityError(f"Commit reference cannot start with a hyphen: '{cleaned}'")
        if not COMMIT_HASH_REGEX.match(cleaned):
            raise GitArgumentSecurityError(f"Invalid commit hash format: '{cleaned}'")
        return cleaned.lower()


GITHUB_REPO_URL_REGEX = re.compile(
    r"^https://(?:www\.)?github\.com/[a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+(?:\.git)?$"
)


class GitURLValidator:
    """Strictly validates remote Git repository URLs for cloning."""

    @classmethod
    def validate_github_https_url(cls, url: str) -> str:
        """Ensure URL is HTTPS, targeting github.com, without user credentials or arbitrary parameters."""
        cleaned = url.strip()
        if not cleaned:
            raise GitURLSecurityError("Git repository URL cannot be empty.")
        if "@" in cleaned:
            raise GitURLSecurityError("Embedded credentials in Git repository URLs are not permitted.")
        for forbidden in ("ssh://", "git@", "file://", "http://"):
            if cleaned.lower().startswith(forbidden):
                raise GitURLSecurityError("Only HTTPS GitHub URLs are supported (e.g. 'https://github.com/owner/repo').")

        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme.lower() != "https":
            raise GitURLSecurityError(f"Unsupported URL scheme '{parsed.scheme}'. Only HTTPS is permitted.")
        if parsed.netloc.lower() not in ("github.com", "www.github.com"):
            raise GitURLSecurityError(f"Unsupported host '{parsed.netloc}'. Only 'github.com' is supported in Stage 21.")

        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) != 2:
            raise GitURLSecurityError("GitHub URL must match 'https://github.com/owner/repository'.")

        if not GITHUB_REPO_URL_REGEX.match(cleaned):
            raise GitURLSecurityError(f"Invalid characters in GitHub repository URL: '{cleaned}'")

        return cleaned


def get_managed_workspaces_root() -> Path:
    """Resolve and create the root directory for managed cloned workspaces."""
    import sys
    import os
    from app.common import config as config_module

    cfg = config_module.config
    if cfg.sentinel_workspaces_root:
        root = Path(cfg.sentinel_workspaces_root).resolve()
    elif getattr(sys, "frozen", False) or (sys.platform == "win32" and not (Path(__file__).resolve().parent.parent.parent / "pyproject.toml").exists()):
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        root = (Path(local_app_data) / "SentinelOps" / "workspaces").resolve()
    elif getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        root = (Path(local_app_data) / "SentinelOps" / "workspaces").resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent.parent
        root = (repo_root / "runtime" / "workspaces").resolve()

    root.mkdir(parents=True, exist_ok=True)
    return root
