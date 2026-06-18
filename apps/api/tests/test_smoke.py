from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


client = TestClient(app)


def run() -> None:
    assert client.get("/health").json() == {"status": "ok"}

    games = client.get("/games")
    assert games.status_code == 200
    assert len(games.json()) >= 3

    manifest = client.get("/play/astro-ludo/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["bundleUrl"].endswith("/bundles/games/astro-ludo/index.html")

    play_event = client.post("/events/play", json={"gameId": "astro-ludo", "event": "game_view"})
    assert play_event.status_code == 200

    unauthenticated_job = client.post("/create/jobs", json={"prompt": "test", "files": []})
    assert unauthenticated_job.status_code == 401

    email = f"smoke-{uuid4().hex[:10]}@yahaha.local"
    auth_register = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "displayName": "Smoke User",
        },
    )
    assert auth_register.status_code == 200
    token = auth_register.json()["accessToken"]
    assert token

    session = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert session.status_code == 200
    assert session.json()["authenticated"] is True

    create_job = client.post(
        "/create/jobs",
        json={"prompt": "test", "files": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_job.status_code == 200
    assert create_job.json()["status"] == "pending"

    logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    logged_out_session = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert logged_out_session.status_code == 200
    assert logged_out_session.json()["authenticated"] is False

    google_start = client.get("/auth/google/start", follow_redirects=False)
    assert google_start.status_code in (302, 307)
    assert "oauth_error=google_not_configured" in google_start.headers["location"]


if __name__ == "__main__":
    run()
    print("api smoke checks passed")
