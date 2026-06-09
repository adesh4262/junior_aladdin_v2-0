"""Floor 2 Replay — session manager.

Provides the **ReplaySessionManager** class that manages replay sessions
— start, stop, status tracking, and session lifecycle.

Responsibilities:
- **Session creation**: Create ``ReplaySession`` instances from queries.
- **Session lifecycle**: Track ACTIVE → COMPLETED / FAILED transitions.
- **Progress tracking**: Update packet replay count per session.
- **Session listing**: List all sessions, filter by status.

Architecture rules:
- Sessions are identified by unique IDs (``sess_<uuid_hex>``).
- Session status transitions are one-way: ACTIVE → COMPLETED or ACTIVE → FAILED.
- A session does NOT execute the replay — it just tracks replay execution
  state. The actual replay logic belongs in ``ReplayEngine``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    ReplayQuery,
    ReplaySession,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("replay_session_manager")

# Valid session statuses
SESSION_ACTIVE = "ACTIVE"
SESSION_COMPLETED = "COMPLETED"
SESSION_FAILED = "FAILED"
_VALID_STATUSES = (SESSION_ACTIVE, SESSION_COMPLETED, SESSION_FAILED)


class ReplaySessionManager:
    """Manages replay session lifecycle.

    Tracks session state (ACTIVE / COMPLETED / FAILED), packet replay
    progress, and provides session listing and filtering.

    Typical usage::

        manager = ReplaySessionManager()
        session = manager.create_session(query)
        manager.complete_session(session.session_id)
        manager.fail_session(session.session_id, "Connection lost")

        # Track progress
        manager.increment_replayed(session.session_id, count=10)

        # List sessions
        all_sessions = manager.list_sessions()
        active = manager.list_sessions(status=SESSION_ACTIVE)
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._sessions: dict[str, ReplaySession] = {}
        # Additional metadata per session (not in ReplaySession dataclass)
        self._metadata: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Session Lifecycle
    # ------------------------------------------------------------------

    def create_session(
        self,
        query: ReplayQuery,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ReplaySession:
        """Create a new replay session.

        Args:
            query: The ``ReplayQuery`` that defines this session.
            session_id: Optional custom session ID. If not provided, one
                is auto-generated.
            metadata: Optional dict with additional session metadata
                (e.g., ``{\"description\": \"morning tick audit\"}``).

        Returns:
            The newly created ``ReplaySession``.
        """
        sid = session_id or _generate_session_id()
        now = datetime.now(timezone.utc)

        session = ReplaySession(
            session_id=sid,
            query=query,
            status=SESSION_ACTIVE,
            packets_replayed=0,
            started_at=now,
        )

        with self._lock:
            self._sessions[sid] = session
            self._metadata[sid] = {
                "created_at": now,
                "updated_at": now,
                "error_message": None,
                **(metadata or {}),
            }

        logger.info(
            "Replay session created",
            extra={
                "session_id": sid,
                "status": SESSION_ACTIVE,
                "sources": query.sources,
                "feed_types": query.feed_types,
                "stage": query.transform_stage.value,
            },
        )
        return session

    def complete_session(self, session_id: str) -> bool:
        """Mark a session as completed.

        Args:
            session_id: The unique session identifier.

        Returns:
            ``True`` if the session was completed, ``False`` if not found
            or already in a terminal state.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.status != SESSION_ACTIVE:
                logger.warning(
                    "Cannot complete session — not active",
                    extra={
                        "session_id": session_id,
                        "current_status": session.status,
                    },
                )
                return False
            session.status = SESSION_COMPLETED
            self._metadata[session_id]["updated_at"] = datetime.now(timezone.utc)

        logger.info(
            "Replay session completed",
            extra={"session_id": session_id, "packets_replayed": session.packets_replayed},
        )
        return True

    def fail_session(
        self,
        session_id: str,
        error_message: str = "Unknown error",
    ) -> bool:
        """Mark a session as failed.

        Args:
            session_id: The unique session identifier.
            error_message: Human-readable error description.

        Returns:
            ``True`` if the session was failed, ``False`` if not found
            or already in a terminal state.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            if session.status != SESSION_ACTIVE:
                logger.warning(
                    "Cannot fail session — not active",
                    extra={
                        "session_id": session_id,
                        "current_status": session.status,
                    },
                )
                return False
            session.status = SESSION_FAILED
            meta = self._metadata.get(session_id, {})
            meta["updated_at"] = datetime.now(timezone.utc)
            meta["error_message"] = error_message

        logger.warning(
            "Replay session failed",
            extra={
                "session_id": session_id,
                "error": error_message,
                "packets_replayed": session.packets_replayed,
            },
        )
        return True

    # ------------------------------------------------------------------
    # Progress Tracking
    # ------------------------------------------------------------------

    def increment_replayed(self, session_id: str, count: int = 1) -> bool:
        """Increment the packets-replayed count for a session.

        Args:
            session_id: The unique session identifier.
            count: Number of packets to add (default 1).

        Returns:
            ``True`` if incremented, ``False`` if session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.packets_replayed += count
            if session_id in self._metadata:
                self._metadata[session_id]["updated_at"] = datetime.now(timezone.utc)
        return True

    def set_replayed_count(self, session_id: str, count: int) -> bool:
        """Set the exact packets-replayed count for a session.

        Args:
            session_id: The unique session identifier.
            count: The exact packet count.

        Returns:
            ``True`` if set, ``False`` if session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.packets_replayed = count
            if session_id in self._metadata:
                self._metadata[session_id]["updated_at"] = datetime.now(timezone.utc)
        return True

    # ------------------------------------------------------------------
    # Session Querying
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> ReplaySession | None:
        """Get a single session by ID.

        Args:
            session_id: The unique session identifier.

        Returns:
            The ``ReplaySession``, or ``None`` if not found.
        """
        with self._lock:
            return self._sessions.get(session_id)

    def get_session_metadata(self, session_id: str) -> dict[str, Any] | None:
        """Get additional metadata for a session.

        Args:
            session_id: The unique session identifier.

        Returns:
            The metadata dict, or ``None`` if session not found.
        """
        with self._lock:
            if session_id not in self._sessions:
                return None
            return dict(self._metadata.get(session_id, {}))

    def list_sessions(
        self,
        status: str | None = None,
    ) -> list[ReplaySession]:
        """List all sessions, optionally filtered by status.

        Args:
            status: Filter by session status (``ACTIVE``, ``COMPLETED``,
                or ``FAILED``). If ``None``, returns all sessions.

        Returns:
            List of ``ReplaySession`` instances (most recent first).
        """
        with self._lock:
            sessions = list(self._sessions.values())

        if status:
            sessions = [s for s in sessions if s.status == status]

        # Sort by started_at descending (most recent first)
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions

    def get_active_sessions(self) -> list[ReplaySession]:
        """Get all currently active sessions.

        Returns:
            List of active ``ReplaySession`` instances.
        """
        return self.list_sessions(status=SESSION_ACTIVE)

    def count_sessions(self, status: str | None = None) -> int:
        """Count sessions, optionally filtered by status.

        Args:
            status: Filter by status. If ``None``, counts all sessions.

        Returns:
            Session count.
        """
        return len(self.list_sessions(status=status))

    def has_active_sessions(self) -> bool:
        """Check if there are any active sessions.

        Returns:
            ``True`` if at least one session is active.
        """
        return len(self.get_active_sessions()) > 0

    # ------------------------------------------------------------------
    # Session Management
    # ------------------------------------------------------------------

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its metadata.

        Args:
            session_id: The unique session identifier.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        with self._lock:
            if session_id not in self._sessions:
                return False
            del self._sessions[session_id]
            self._metadata.pop(session_id, None)
        logger.debug("Replay session deleted", extra={"session_id": session_id})
        return True

    def clear(self) -> None:
        """Remove ALL sessions and metadata."""
        with self._lock:
            self._sessions.clear()
            self._metadata.clear()
        logger.info("ReplaySessionManager cleared")

    def get_session_summary(self, session_id: str) -> dict[str, Any] | None:
        """Get a comprehensive summary of a session.

        Combines the ``ReplaySession`` fields with metadata.

        Args:
            session_id: The unique session identifier.

        Returns:
            A dict with session summary, or ``None`` if not found.
        """
        session = self.get_session(session_id)
        if session is None:
            return None
        meta = self.get_session_metadata(session_id) or {}

        return {
            "session_id": session.session_id,
            "status": session.status,
            "packets_replayed": session.packets_replayed,
            "started_at": session.started_at.isoformat(),
            "query": {
                "start_time": session.query.start_time.isoformat() if session.query.start_time else None,
                "end_time": session.query.end_time.isoformat() if session.query.end_time else None,
                "sources": session.query.sources,
                "feed_types": session.query.feed_types,
                "transform_stage": session.query.transform_stage.value,
            },
            "error_message": meta.get("error_message"),
            "description": meta.get("description"),
            "created_at": meta.get("created_at").isoformat() if meta.get("created_at") else None,
            "updated_at": meta.get("updated_at").isoformat() if meta.get("updated_at") else None,
        }


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"sess_{uuid.uuid4().hex[:12]}"
