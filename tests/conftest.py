"""Global pytest configuration and automatic test-isolation fixture for SentinelOps."""

from pathlib import Path
import pytest

from app.actions.dependencies import close_action_store, set_custom_action_db_path
from app.agents.dependencies import close_investigation_repository, set_custom_investigation_db_path
from app.incidents.dependencies import close_incident_repository, set_custom_incident_db_path
from app.memory.dependencies import close_memory_repository, set_custom_memory_db_path
from app.notifications.dependencies import close_notification_store, set_custom_notification_db_path
from app.remediation.dependencies import close_remediation_repositories, set_custom_remediation_db_path
from app.telemetry.dependencies import close_evidence_repository, set_custom_evidence_db_path


@pytest.fixture(autouse=True)
def isolate_stage19_sqlite_databases(tmp_path):
    """Ensure all tests operate on an isolated temporary SQLite database by default.

    Prevents any test fixture or teardown from attempting to clear or mutate the
    production database at runtime/sentinelops.db.
    """
    test_db = str(tmp_path / "sentinelops_autouse_test.db")

    set_custom_incident_db_path(test_db)
    set_custom_evidence_db_path(test_db)
    set_custom_investigation_db_path(test_db)
    set_custom_remediation_db_path(test_db)
    set_custom_action_db_path(test_db)
    set_custom_notification_db_path(test_db)
    set_custom_memory_db_path(test_db)

    yield

    close_remediation_repositories()
    close_investigation_repository()
    close_evidence_repository()
    close_memory_repository()
    close_action_store()
    close_notification_store()
    close_incident_repository()

    set_custom_incident_db_path(None)
    set_custom_evidence_db_path(None)
    set_custom_investigation_db_path(None)
    set_custom_remediation_db_path(None)
    set_custom_action_db_path(None)
    set_custom_notification_db_path(None)
    set_custom_memory_db_path(None)
