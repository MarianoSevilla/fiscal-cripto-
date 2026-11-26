"""Single-execution claims for credit-backed FIFO analyses.

PostgreSQL session advisory locks are held for the complete Flask request. If
the worker exits, PostgreSQL releases its lock; recovery can then distinguish
an idle reservation from an interrupted execution without a timeout guess.
The in-process lock fallback exists only for isolated SQLite unit tests.
"""
from __future__ import annotations

from threading import Lock
from uuid import UUID

from sqlalchemy import text

from models import db


_fallback_guard = Lock()
_fallback_locks: dict[tuple[int, str], Lock] = {}
_PG_LOCK_SEED = 0x435245444954


class AnalysisExecutionLock:
    def __init__(self, *, user_id: int, analysis_id: str, connection=None, fallback=None):
        self.user_id = user_id
        self.analysis_id = analysis_id
        self._connection = connection
        self._fallback = fallback
        self._released = False

    def matches(self, *, user_id: int, analysis_id: str) -> bool:
        return (not self._released and self.user_id == user_id
                and self.analysis_id == analysis_id)

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self._fallback is not None:
            self._fallback.release()
            return
        connection = self._connection
        self._connection = None
        if connection is None:
            return
        try:
            key = _pg_lock_key(self.user_id, self.analysis_id)
            unlocked = connection.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, :seed))"),
                {"lock_key": key, "seed": _PG_LOCK_SEED},
            ).scalar_one()
            connection.commit()
            if not unlocked:
                raise RuntimeError("credit execution lock was not held")
        except Exception:
            # A DBAPI connection returned to the pool can retain a session-level
            # advisory lock across rollback. Discard it on uncertain unlock so
            # the pool can never hand a stale lock-holding session to another request.
            connection.invalidate()
            raise
        finally:
            connection.close()


def _pg_lock_key(user_id: int, analysis_id: str) -> str:
    # Credit analysis IDs are generated as UUIDs; parsing rejects malformed
    # request IDs before a lock can be created.
    normalized = str(UUID(analysis_id))
    return f"marianosevilla:credit-analysis:{user_id}:{normalized}"


def try_acquire_analysis_lock(*, user_id: int, analysis_id: str) -> AnalysisExecutionLock | None:
    """Acquire the per-analysis lock without waiting; return None if active."""
    key = _pg_lock_key(user_id, analysis_id)
    if db.engine.dialect.name == "postgresql":
        connection = db.engine.connect()
        try:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(hashtextextended(:lock_key, :seed))"),
                {"lock_key": key, "seed": _PG_LOCK_SEED},
            ).scalar_one()
            connection.commit()  # session lock survives transaction boundaries
            if not acquired:
                connection.close()
                return None
            return AnalysisExecutionLock(
                user_id=user_id, analysis_id=str(UUID(analysis_id)),
                connection=connection,
            )
        except Exception:
            # The server may have granted the session lock before the client
            # observed a network/commit error. Closing to the pool alone would
            # not release a PostgreSQL session advisory lock.
            connection.invalidate()
            connection.close()
            raise

    # Tests using SQLite do not claim cross-process safety. Production readiness
    # requires PostgreSQL; these locks still exercise same-process request races.
    fallback_key = (user_id, str(UUID(analysis_id)))
    with _fallback_guard:
        lock = _fallback_locks.setdefault(fallback_key, Lock())
    if not lock.acquire(blocking=False):
        return None
    return AnalysisExecutionLock(
        user_id=user_id, analysis_id=fallback_key[1], fallback=lock,
    )
