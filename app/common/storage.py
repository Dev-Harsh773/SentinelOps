"""Initialize every durable domain before accepting production traffic."""


def initialize_storage() -> None:
    from app.actions.dependencies import get_action_store
    from app.agents.dependencies import get_investigation_repository
    from app.connectors.dependencies import get_connector_store
    from app.incidents.dependencies import get_incident_repository
    from app.memory.dependencies import get_memory_repository
    from app.notifications.dependencies import get_notification_store
    from app.projects.dependencies import get_project_store
    from app.remediation.dependencies import (
        get_remediation_repository, get_review_repository, get_branch_repository,
    )
    from app.telemetry.dependencies import get_evidence_repository
    from app.watcher.dependencies import get_watcher_storage

    for factory in (
        get_action_store, get_investigation_repository, get_connector_store,
        get_incident_repository, get_memory_repository, get_notification_store,
        get_project_store, get_remediation_repository, get_review_repository,
        get_branch_repository, get_evidence_repository, get_watcher_storage,
    ):
        factory()
