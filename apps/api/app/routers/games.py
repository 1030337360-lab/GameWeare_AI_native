from fastapi import APIRouter, HTTPException

from app.schemas import Game
from app.services.catalog import get_game, list_games

router = APIRouter(prefix="/games", tags=["games"])


@router.get("", response_model=list[Game])
def games() -> list[Game]:
    return list_games()


@router.get("/{game_id}", response_model=Game)
def game_detail(game_id: str) -> Game:
    game = get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game
