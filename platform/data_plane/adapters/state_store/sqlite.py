"""SQLite adapter for StateStorePort."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from data_plane.ports.state_store import StateStorePort
from shared.domain.conversation import ConversationState

log = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_states (
    tenant_id     TEXT NOT NULL,
    contact_id    TEXT NOT NULL,
    current_state TEXT NOT NULL,
    data          TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (tenant_id, contact_id)
);
"""

_PRAGMA_WAL = "PRAGMA journal_mode=WAL;"


class SQLiteStateStore(StateStorePort):
    """SQLite-backed conversation state store."""

    def __init__(self, db_path: str = "/data/state.db") -> None:
        self._db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(_CREATE_TABLE)
            conn.execute(_PRAGMA_WAL)
            conn.commit()
            conn.close()
        except Exception:
            log.exception("[SQLITE_STATE_STORE] Failed to initialise schema")

    def get(self, tenant_id: str, contact_id: str) -> ConversationState | None:
        try:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute(
                "SELECT current_state, data, created_at, updated_at "
                "FROM conversation_states "
                "WHERE tenant_id = ? AND contact_id = ?",
                (tenant_id, contact_id),
            ).fetchone()
            conn.close()
            if row is None:
                return None
            current_state, data_json, created_at_str, updated_at_str = row
            return ConversationState(
                tenant_id=tenant_id,
                contact_id=contact_id,
                current_state=current_state,
                data=json.loads(data_json),
                created_at=datetime.fromisoformat(created_at_str),
                updated_at=datetime.fromisoformat(updated_at_str),
            )
        except Exception:
            log.exception("[SQLITE_STATE_STORE] get failed for %s/%s", tenant_id, contact_id)
            return None

    def save(self, state: ConversationState) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO conversation_states "
                "(tenant_id, contact_id, current_state, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    state.tenant_id,
                    state.contact_id,
                    state.current_state,
                    json.dumps(state.data),
                    state.created_at.isoformat(),
                    state.updated_at.isoformat(),
                ),
            )
            conn.commit()
            conn.close()
        except Exception:
            log.exception(
                "[SQLITE_STATE_STORE] save failed for %s/%s",
                state.tenant_id,
                state.contact_id,
            )

    def delete(self, tenant_id: str, contact_id: str) -> None:
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "DELETE FROM conversation_states WHERE tenant_id = ? AND contact_id = ?",
                (tenant_id, contact_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            log.exception("[SQLITE_STATE_STORE] delete failed for %s/%s", tenant_id, contact_id)
