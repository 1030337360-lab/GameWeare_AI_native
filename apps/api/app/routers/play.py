from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse

from app.schemas import GameManifest, PlayEvent
from app.services.auth_service import get_optional_user
from app.services.catalog import ensure_catalog_runtime_schema, get_game_document, get_game_manifest
from app.services.play_stats_service import record_play_event

router = APIRouter(tags=["play"])


@router.get("/play/{game_id}/manifest", response_model=GameManifest)
def manifest(game_id: str) -> GameManifest:
    game_manifest = get_game_manifest(game_id)
    if not game_manifest:
        raise HTTPException(status_code=404, detail="Game not found")
    return game_manifest


@router.get("/play/{game_id}/document", response_class=HTMLResponse, include_in_schema=False)
def game_document(game_id: str) -> str:
    document = get_game_document(game_id)
    if not document:
        raise HTTPException(status_code=404, detail="Game document not found")
    return document


@router.post("/events/play")
def play_event(event: PlayEvent, user=Depends(get_optional_user)) -> dict[str, str | bool]:
    ensure_catalog_runtime_schema()
    result = record_play_event(event, user)
    if result["status"] == "missing":
        raise HTTPException(status_code=404, detail="Game not found")
    return result
