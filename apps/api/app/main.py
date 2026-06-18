from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.routers import auth, create, games, play, uploads

app = FastAPI(title="Yahaha MVP API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1314", "http://127.0.0.1:1314"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(games.router)
app.include_router(play.router)
app.include_router(create.router)
app.include_router(uploads.router)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/bundles/games/{game_id}/index.html", response_class=HTMLResponse, include_in_schema=False)
def generated_game(game_id: str) -> str:
    title = game_id.replace("-", " ").title()
    return f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        background: radial-gradient(circle at 35% 20%, #5eead4, transparent 30rem), #090b12;
        color: white;
        font-family: Inter, system-ui, sans-serif;
      }}
      .game {{
        width: min(760px, 90vw);
        border: 1px solid rgba(255,255,255,.18);
        border-radius: 12px;
        padding: 32px;
        background: rgba(10,12,20,.78);
        text-align: center;
      }}
      button {{
        border: 0;
        border-radius: 999px;
        padding: 12px 20px;
        font-weight: 800;
      }}
    </style>
  </head>
  <body>
    <main class="game">
      <p>Remote manifest demo</p>
      <h1>{title}</h1>
      <p>This HTML is served through the backend as a stand-in for a MinIO-hosted game bundle.</p>
      <button onclick="document.querySelector('h1').textContent='Playing {title}'">Play</button>
    </main>
  </body>
</html>
"""


STATIC_ROOT = Path(__file__).resolve().parent / "static"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
