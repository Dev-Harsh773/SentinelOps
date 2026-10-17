"""Incident lifecycle intents written using the incident's SQLite transaction.

Subscription snapshots preserve the policy/destination in force at event time.
Delivery never runs in this transaction. Replay is safe via notification dedup keys.
"""
from dataclasses import asdict
from enum import Enum
import json


def initialize_outbox(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS notification_outbox (
        event_key TEXT PRIMARY KEY, incident_json TEXT NOT NULL,
        subscriptions_json TEXT NOT NULL, processed_at TEXT
    )""")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_notification_outbox_pending ON notification_outbox(processed_at)")


def record_intent(connection, incident):
    if incident.status.value not in ("open", "resolved", "closed"):
        return
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='notification_subscriptions'").fetchone()
    subscriptions = []
    if exists:
        subscriptions = [dict(r) for r in connection.execute(
            "SELECT * FROM notification_subscriptions WHERE project_id=? AND enabled=1",
            (incident.project_id,)).fetchall()]
    def encode(value):
        return value.value if isinstance(value, Enum) else value.isoformat()
    connection.execute("""INSERT OR IGNORE INTO notification_outbox
        (event_key,incident_json,subscriptions_json) VALUES (?,?,?)""",
        (f"{incident.project_id}:{incident.id}:{incident.status.value}",
         json.dumps(asdict(incident), default=encode), json.dumps(subscriptions)))
