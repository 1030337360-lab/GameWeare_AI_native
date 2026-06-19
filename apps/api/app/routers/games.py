from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas import Game, GameInteractionState
from app.services.auth_service import get_optional_user, require_user
from app.services.catalog import ensure_catalog_runtime_schema, get_game, list_games, list_tags, set_game_favorite, set_game_like

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
