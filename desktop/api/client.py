"""HTTP API client for SentinelOps backend communications.

Pure consumer wrapping httpx without importing any backend application code.
Converts HTTP errors to typed SentinelOps exceptions.
"""

from typing import Any, Dict, List, Optional
import httpx

from desktop.api.exceptions import (
    BackendUnavailableError,
    ConflictError,
    NotFoundError,
    SentinelOpsApiError,
    ServerError,
    ValidationError,
)
from desktop.api.models import (
    ConnectorDTO,
    EvidenceDTO,
    IncidentDTO,
    InvestigationDTO,
    NotificationDTO,
    ProjectDTO,
    ProjectKnowledgeDTO,
    RemediationBranchDTO,
    RemediationDTO,
    RemediationReviewDTO,
    WatcherStatusDTO,
)


class SentinelOpsClient:
    """Synchronous HTTP client for interacting with SentinelOps backend."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 5.0,
        reindex_timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.reindex_timeout = reindex_timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=transport,
            headers={"User-Agent": "SentinelOps-ControlCenter/0.1.0"},
        )

    def close(self) -> None:
        """Close underlying HTTP client connections."""
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Execute HTTP request with deterministic exception mapping."""
        req_timeout = timeout or self.timeout
        try:
            resp = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json,
                timeout=req_timeout,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise BackendUnavailableError(
                f"Backend unreachable at {self.base_url}: {exc}",
                detail=str(exc),
            ) from exc
        except Exception as exc:
            raise SentinelOpsApiError(f"HTTP request error: {exc}", detail=str(exc)) from exc

        if resp.status_code in (200, 201):
            return resp.json() if resp.content else {}
        if resp.status_code == 204:
            return None

        # Extract backend error detail string safely
        detail = ""
        try:
            err_json = resp.json()
            if isinstance(err_json, dict):
                detail = err_json.get("detail", str(err_json))
            else:
                detail = str(err_json)
        except Exception:
            detail = resp.text

        msg = f"HTTP {resp.status_code}: {detail or resp.reason_phrase}"
        if resp.status_code == 404:
            raise NotFoundError(msg, status_code=404, detail=detail)
        if resp.status_code == 409:
            raise ConflictError(msg, status_code=409, detail=detail)
        if resp.status_code in (400, 422):
            raise ValidationError(msg, status_code=resp.status_code, detail=detail)
        if resp.status_code >= 500:
            raise ServerError(msg, status_code=resp.status_code, detail=detail)

        raise SentinelOpsApiError(msg, status_code=resp.status_code, detail=detail)

    # -------------------------------------------------------------------------
    # Health & Watcher
    # -------------------------------------------------------------------------

    def get_health(self) -> Dict[str, str]:
        """Verify service liveness."""
        return self._request("GET", "/health")

    def get_watcher_status(self) -> WatcherStatusDTO:
        """Fetch Sentinel Watcher runtime telemetry status."""
        data = self._request("GET", "/watcher/status")
        return WatcherStatusDTO.from_dict(data)

    # -------------------------------------------------------------------------
    # Projects
    # -------------------------------------------------------------------------

    def list_projects(self) -> List[ProjectDTO]:
        """Fetch all onboarded projects."""
        data = self._request("GET", "/projects")
        return [ProjectDTO.from_dict(p) for p in data]

    def get_project(self, project_id: str) -> ProjectDTO:
        """Fetch single project details."""
        data = self._request("GET", f"/projects/{project_id}")
        return ProjectDTO.from_dict(data)

    def get_project_knowledge(self, project_id: str) -> ProjectKnowledgeDTO:
        """Fetch project knowledge snapshot."""
        data = self._request("GET", f"/projects/{project_id}/knowledge")
        return ProjectKnowledgeDTO.from_dict(data)

    def reindex_project(self, project_id: str) -> ProjectKnowledgeDTO:
        """Trigger project workspace reindex with extended timeout."""
        data = self._request("POST", f"/projects/{project_id}/reindex", timeout=self.reindex_timeout)
        return ProjectKnowledgeDTO.from_dict(data)

    # -------------------------------------------------------------------------
    # Incidents
    # -------------------------------------------------------------------------

    def list_incidents(self) -> List[IncidentDTO]:
        """Fetch all incidents (caller may filter by project_id)."""
        data = self._request("GET", "/incidents")
        return [IncidentDTO.from_dict(i) for i in data]

    def get_incident(self, incident_id: str) -> IncidentDTO:
        """Fetch single incident details."""
        data = self._request("GET", f"/incidents/{incident_id}")
        return IncidentDTO.from_dict(data)

    def update_incident_status(self, incident_id: str, status: str) -> IncidentDTO:
        """Transition incident lifecycle status."""
        data = self._request("PATCH", f"/incidents/{incident_id}/status", json={"status": status})
        return IncidentDTO.from_dict(data)

    def list_incident_evidence(self, incident_id: str) -> List[EvidenceDTO]:
        """Fetch runtime log evidence attached to an incident."""
        data = self._request("GET", f"/incidents/{incident_id}/evidence")
        return [EvidenceDTO.from_dict(e) for e in data]

    def get_incident_investigation(self, incident_id: str) -> Optional[InvestigationDTO]:
        """Fetch AI investigation analysis if present, or None if not run."""
        try:
            data = self._request("GET", f"/incidents/{incident_id}/investigation")
            return InvestigationDTO.from_dict(data)
        except NotFoundError:
            return None

    def get_incident_remediation(self, incident_id: str) -> Optional[RemediationDTO]:
        """Fetch proposed remediation if present, or None if not proposed."""
        try:
            data = self._request("GET", f"/incidents/{incident_id}/remediation")
            return RemediationDTO.from_dict(data)
        except NotFoundError:
            return None

    def list_remediation_reviews(self, incident_id: str) -> List[RemediationReviewDTO]:
        """Fetch human review audit history for incident remediation."""
        try:
            data = self._request("GET", f"/incidents/{incident_id}/remediation/reviews")
            return [RemediationReviewDTO.from_dict(r) for r in data]
        except NotFoundError:
            return []

    def get_remediation_branch(self, incident_id: str) -> Optional[RemediationBranchDTO]:
        """Fetch active branch information if created."""
        try:
            data = self._request("GET", f"/incidents/{incident_id}/remediation/branch")
            return RemediationBranchDTO.from_dict(data)
        except NotFoundError:
            return None

    # -------------------------------------------------------------------------
    # Notifications
    # -------------------------------------------------------------------------

    def list_notifications(
        self,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        read_status: Optional[str] = None,
    ) -> List[NotificationDTO]:
        """Fetch paginated notification feed."""
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if project_id:
            params["project_id"] = project_id
        if read_status:
            params["read_status"] = read_status
        data = self._request("GET", "/notifications", params=params)
        return [NotificationDTO.from_dict(n) for n in data]

    def mark_notification_read(self, notification_id: str) -> NotificationDTO:
        """Mark a single notification as read."""
        data = self._request("PATCH", f"/notifications/{notification_id}/read")
        return NotificationDTO.from_dict(data)

    def mark_all_notifications_read(self, project_id: str) -> Dict[str, Any]:
        """Mark all unread notifications for a project as read."""
        return self._request("POST", "/notifications/mark-all-read", params={"project_id": project_id})

    def retry_notification(self, notification_id: str) -> NotificationDTO:
        """Retry a failed webhook notification."""
        data = self._request("POST", f"/notifications/{notification_id}/retry")
        return NotificationDTO.from_dict(data)

    # -------------------------------------------------------------------------
    # Connectors
    # -------------------------------------------------------------------------

    def list_connectors(self, project_id: Optional[str] = None) -> List[ConnectorDTO]:
        """Fetch registered telemetry/deployment connectors."""
        params = {"project_id": project_id} if project_id else None
        data = self._request("GET", "/connectors", params=params)
        return [ConnectorDTO.from_dict(c) for c in data]

    def test_connector(self, connector_id: str) -> Dict[str, Any]:
        """Perform non-mutating connectivity test."""
        return self._request("POST", f"/connectors/{connector_id}/test")
