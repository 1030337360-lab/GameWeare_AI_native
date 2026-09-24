from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.schemas import Game, GameDeleteResult, GameInteractionState, GameVersionSummary, GameVersionSwitchRequest, RemixResponse
from app.services.auth_service import get_optional_user, require_user
from app.services.catalog import (
    delete_owned_game,
    ensure_catalog_runtime_schema,
    get_game,
    get_game_cover,
    list_game_versions,
    list_games,
    list_tags,
    remix_game,
    set_game_favorite,
    set_game_like,
    switch_game_version,
)

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=list[Game])
def games(
    q: str | None = Query(None),
    tag: str | None = Query(None),
    user=Depends(get_optional_user),
) -> list[Game]:
    ensure_catalog_runtime_schema()
    return list_games(query=q, tag=tag, user_id=user.id if user else None)


@router.get("/tags", response_model=list[str])
def game_tags() -> list[str]:
    ensure_catalog_runtime_schema()
    return list_tags()


@router.get("/{game_id}", response_model=Game)
def game_detail(game_id: str, user=Depends(get_optional_user)) -> Game:
    ensure_catalog_runtime_schema()
    game = get_game(game_id, user_id=user.id if user else None)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game


@router.delete("/{game_id}", response_model=GameDeleteResult)
def delete_game(game_id: str, user=Depends(require_user)) -> GameDeleteResult:
    ensure_catalog_runtime_schema()
    result = delete_owned_game(game_id, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    return result


@router.get("/{game_id}/cover", include_in_schema=False)
def game_cover(game_id: str) -> Response:
    ensure_catalog_runtime_schema()
    cover = get_game_cover(game_id)
    if not cover:
        raise HTTPException(status_code=404, detail="Game cover not found")
    content, content_type = cover
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{game_id}/versions", response_model=list[GameVersionSummary])
def game_versions(game_id: str) -> list[GameVersionSummary]:
    ensure_catalog_runtime_schema()
    versions = list_game_versions(game_id)
    if not versions:
        raise HTTPException(status_code=404, detail="Game versions not found")
    return versions


@router.post("/{game_id}/versions/switch", response_model=list[GameVersionSummary])
def switch_version(game_id: str, payload: GameVersionSwitchRequest, user=Depends(require_user)) -> list[GameVersionSummary]:
    ensure_catalog_runtime_schema()
    versions = switch_game_version(game_id, version_id=payload.versionId, user_id=user.id)
    if not versions:
        raise HTTPException(status_code=404, detail="Game version not found")
    return versions


@router.post("/{game_id}/remix", response_model=RemixResponse)
def remix(game_id: str, user=Depends(require_user)) -> RemixResponse:
    ensure_catalog_runtime_schema()
    result = remix_game(game_id, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="Game not found")
    return result


@router.put("/{game_id}/like", response_model=GameInteractionState)
def like_game(game_id: str, user=Depends(require_user)) -> GameInteractionState:
    ensure_catalog_runtime_schema()
    state = set_game_like(game_id, user_id=user.id, liked=True)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


@router.delete("/{game_id}/like", response_model=GameInteractionState)
def unlike_game(game_id: str, user=Depends(require_user)) -> GameInteractionState:
    ensure_catalog_runtime_schema()
    state = set_game_like(game_id, user_id=user.id, liked=False)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


@router.put("/{game_id}/favorite", response_model=GameInteractionState)
def favorite_game(game_id: str, user=Depends(require_user)) -> GameInteractionState:
    ensure_catalog_runtime_schema()
    state = set_game_favorite(game_id, user_id=user.id, favorited=True)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state


@router.delete("/{game_id}/favorite", response_model=GameInteractionState)
def unfavorite_game(game_id: str, user=Depends(require_user)) -> GameInteractionState:
    ensure_catalog_runtime_schema()
    state = set_game_favorite(game_id, user_id=user.id, favorited=False)
    if not state:
        raise HTTPException(status_code=404, detail="Game not found")
    return state
