from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb

from app.database import db_connection
from app.schemas import GameManifest, PlayEvent
from app.services.catalog import get_game_manifest

router = APIRouter(tags=["play"])


@router.get("/play/{game_id}/manifest", response_model=GameManifest)
def manifest(game_id: str) -> GameManifest:
    game_manifest = get_game_manifest(game_id)
    if not game_manifest:
        raise HTTPException(status_code=404, detail="Game not found")
    return game_manifest


@router.post("/events/play")
def play_event(event: PlayEvent) -> dict[str, str]:
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
            raise HTTPException(status_code=404, detail="Game not found")
        connection.execute(
            """
INSERT INTO play_events (
  game_id,
  version_id,
  event_type,
  duration_ms,
  error_message,
  metadata,
  created_at
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
""",
            (
                game["id"],
                game["current_version_id"],
                event.event,
                event.durationMs,
                event.errorMessage,
                Jsonb(event.metadata),
                event.occurredAt,
            ),
        )
        if event.event == "game_start":
            connection.execute(
                "UPDATE games SET plays_count = plays_count + 1 WHERE id = %s",
                (game["id"],),
            )
    return {"status": "accepted", "gameId": event.gameId, "event": event.event}
