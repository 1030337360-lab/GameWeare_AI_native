from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.schemas import GameManifest, PlayEvent
from app.services.catalog import get_game

router = APIRouter(tags=["play"])


@router.get("/play/{game_id}/manifest", response_model=GameManifest)
def manifest(game_id: str) -> GameManifest:
    game = get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    settings = get_settings()
    bundle_url = f"http://localhost:{settings.api_port}/bundles/games/{game.id}/index.html"
    return GameManifest(
        id=game.id,
        title=game.title,
        bundleUrl=bundle_url,
        assets=[game.coverUrl],
    )


@router.post("/events/play")
def play_event(event: PlayEvent) -> dict[str, str]:
    return {"status": "accepted", "gameId": event.gameId, "event": event.event}
