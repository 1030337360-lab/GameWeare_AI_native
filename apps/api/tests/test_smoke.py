from pathlib import Path
import sys

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

    create_job = client.post("/create/jobs", json={"prompt": "test", "files": []})
    assert create_job.status_code == 200
    assert create_job.json()["status"] == "stubbed"


if __name__ == "__main__":
    run()
    print("api smoke checks passed")
