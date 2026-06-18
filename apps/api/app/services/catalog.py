from datetime import datetime, timezone

from app.schemas import Game


GAMES: list[Game] = [
    Game(
        id="astro-ludo",
        title="Astro Ludo",
        author="xiaoling",
        description="Fast tabletop moves in a glowing space arcade.",
        tags=["Board", "Arcade"],
        publishedAt=datetime(2026, 6, 18, 10, 0, tzinfo=timezone.utc),
        coverUrl="https://images.unsplash.com/photo-1614728894747-a83421e2b9c9?auto=format&fit=crop&w=900&q=80",
        plays=1200000,
        section="Players' Choice",
    ),
    Game(
        id="color-bloom",
        title="Color Bloom",
        author="emanfatima",
        description="A bright matching puzzle generated from a single prompt.",
        tags=["Puzzle", "Generated"],
        publishedAt=datetime(2026, 6, 18, 11, 0, tzinfo=timezone.utc),
        coverUrl="https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=900&q=80",
        plays=700000,
        section="Trending",
    ),
    Game(
        id="rail-in-air",
        title="Rail in Air",
        author="Majisok",
        description="Balance a flying rail cart through neon gates.",
        tags=["Runner", "Physics"],
        publishedAt=datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc),
        coverUrl="https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=80",
        plays=4500000,
        section="Recommended For You",
    ),
]


def list_games() -> list[Game]:
    return GAMES


def get_game(game_id: str) -> Game | None:
    return next((game for game in GAMES if game.id == game_id), None)
