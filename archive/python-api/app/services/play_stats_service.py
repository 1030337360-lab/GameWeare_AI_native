from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from app.config import get_settings
from app.database import db_connection
from app.schemas import PlayEvent, UserProfile
from app.services.auth_service import redis_client

PENDING_PLAYS_KEY = "play:pending-counts"
REALTIME_PLAYS_KEY = "play:realtime-counts"
_FLUSH_THREAD: threading.Thread | None = None
_STOP_EVENT: threading.Event | None = None
_THREAD_LOCK = threading.Lock()


def _identity_params(user: UserProfile | None, anonymous_id: str | None) -> tuple[str | None, str | None]:
    return (user.id if user else None, None if user else anonymous_id)


def _has_recent_start(
    connection: Any,
    *,
    game_id: str,
    occurred_at: datetime,
    user_id: str | None,
    anonymous_id: str | None,
) -> bool:
    if not user_id and not anonymous_id:
        return False
    row = connection.execute(
        """
SELECT id
FROM play_events
WHERE
  game_id = %s
  AND event_type IN ('game_view', 'game_start')
  AND created_at >= (%s::timestamptz - interval '1 day')
  AND (
    (%s::uuid IS NOT NULL AND user_id = %s::uuid)
    OR (%s::uuid IS NULL AND %s::uuid IS NOT NULL AND anonymous_id = %s::uuid)
  )
ORDER BY created_at
LIMIT 1
""",
        (game_id, occurred_at, user_id, user_id, user_id, anonymous_id, anonymous_id),
    ).fetchone()
    return row is not None


def _should_count_event(event: PlayEvent) -> bool:
    return event.event in {"game_view", "game_start"}


def record_play_event(event: PlayEvent, user: UserProfile | None = None) -> dict[str, str | bool]:
    with db_connection() as connection:
        game = connection.execute(
            """
SELECT id, current_version_id
FROM games
WHERE slug = %s AND deleted_at IS NULL
LIMIT 1
""",
            (event.gameId,),
        ).fetchone()
        if not game:
            return {"status": "missing", "gameId": event.gameId, "event": event.event, "counted": False}

        user_id, anonymous_id = _identity_params(user, event.anonymousId)
        counted = False
        if _should_count_event(event) and (user_id or anonymous_id):
            counted = not _has_recent_start(
                connection,
                game_id=game["id"],
                occurred_at=event.occurredAt,
                user_id=user_id,
                anonymous_id=anonymous_id,
            )

        connection.execute(
            """
INSERT INTO play_events (
  user_id,
  anonymous_id,
  game_id,
  version_id,
  event_type,
  duration_ms,
  error_message,
  metadata,
  created_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
""",
            (
                user_id,
                anonymous_id,
                game["id"],
                game["current_version_id"],
                event.event,
                event.durationMs,
                event.errorMessage,
                Jsonb(event.metadata),
                event.occurredAt,
            ),
        )

    if counted:
        client = redis_client()
        client.hincrby(PENDING_PLAYS_KEY, str(game["id"]), 1)
        client.hincrby(REALTIME_PLAYS_KEY, str(game["id"]), 1)
    return {"status": "accepted", "gameId": event.gameId, "event": event.event, "counted": counted}


def realtime_play_counts(game_ids: list[str]) -> dict[str, int]:
    if not game_ids:
        return {}
    values = redis_client().hmget(REALTIME_PLAYS_KEY, game_ids)
    result: dict[str, int] = {}
    for game_id, value in zip(game_ids, values):
        try:
            result[game_id] = int(value or 0)
        except (TypeError, ValueError):
            result[game_id] = 0
    return result


def pending_play_counts(game_ids: list[str]) -> dict[str, int]:
    return realtime_play_counts(game_ids)


def flush_pending_play_counts() -> dict[str, int]:
    client = redis_client()
    pending = client.hgetall(PENDING_PLAYS_KEY)
    if not pending:
        return {}

    applied: dict[str, int] = {}
    with db_connection() as connection:
        for game_id, raw_delta in pending.items():
            try:
                delta = int(raw_delta)
            except (TypeError, ValueError):
                client.hdel(PENDING_PLAYS_KEY, game_id)
                continue
            if delta <= 0:
                client.hdel(PENDING_PLAYS_KEY, game_id)
                continue
            updated = connection.execute(
                """
UPDATE games
SET plays_count = plays_count + %s
WHERE id = %s
RETURNING id
""",
                (delta, game_id),
            ).fetchone()
            if updated:
                applied[game_id] = delta
                current = client.hincrby(REALTIME_PLAYS_KEY, game_id, -delta)
                if current <= 0:
                    client.hdel(REALTIME_PLAYS_KEY, game_id)
            client.hdel(PENDING_PLAYS_KEY, game_id)
    return applied


def _flush_loop(stop_event: threading.Event) -> None:
    interval = max(1.0, float(get_settings().play_stats_flush_interval_seconds))
    while not stop_event.wait(interval):
        try:
            flush_pending_play_counts()
        except Exception:
            continue


def start_play_stats_flush_thread() -> None:
    global _FLUSH_THREAD, _STOP_EVENT
    with _THREAD_LOCK:
        if _FLUSH_THREAD and _FLUSH_THREAD.is_alive():
            return
        _STOP_EVENT = threading.Event()
        _FLUSH_THREAD = threading.Thread(target=_flush_loop, args=(_STOP_EVENT,), name="play-stats-flusher", daemon=True)
        _FLUSH_THREAD.start()


def stop_play_stats_flush_thread() -> None:
    global _FLUSH_THREAD, _STOP_EVENT
    with _THREAD_LOCK:
        if _STOP_EVENT:
            _STOP_EVENT.set()
        if _FLUSH_THREAD and _FLUSH_THREAD.is_alive():
            _FLUSH_THREAD.join(timeout=2.0)
        _STOP_EVENT = None
        _FLUSH_THREAD = None
