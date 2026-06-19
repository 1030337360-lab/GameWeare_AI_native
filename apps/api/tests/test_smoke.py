from pathlib import Path
import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["CREATE_VALIDATE_LLM_CONFIG"] = "false"
os.environ["CREATE_STATIC_GENERATION"] = "true"

from app.main import app


client = TestClient(app)


def run() -> None:
    assert client.get("/health").json() == {"status": "ok"}

    public_ai_config = client.get("/create/ai-config")
    assert public_ai_config.status_code == 200
    assert public_ai_config.json() == {"authenticated": False, "configured": False, "baseUrl": None, "model": None, "provider": None, "staticGeneration": True}

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
    assert create_job.status_code == 409
    assert create_job.json()["detail"]["code"] == "AI_CONFIG_REQUIRED"

    ai_config = client.put(
        "/create/ai-config",
        json={
            "baseUrl": "https://api.example.test/v1",
            "model": "test-model",
            "apiKey": "test-api-key",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ai_config.status_code == 200
    ai_config_payload = ai_config.json()
    assert ai_config_payload["configured"] is True
    assert ai_config_payload["baseUrl"] == "https://api.example.test/v1"
    assert "apiKey" not in ai_config_payload

    create_job = client.post(
        "/create/jobs",
        json={"prompt": "collect bright stars with pointer controls", "files": [], "agentMode": "opt", "createType": "init"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_job.status_code == 202
    create_payload = create_job.json()
    assert create_payload["status"] == "planning"
    assert create_payload["agentMode"] == "opt"
    assert create_payload["createType"] == "init"
    assert create_payload["projectId"]
    assert create_payload["runId"]
    assert create_payload["taskId"]
    assert create_payload["resumeStatus"] == "fresh"
    completed_job = client.get(f"/create/jobs/{create_payload['id']}", headers={"Authorization": f"Bearer {token}"})
    assert completed_job.status_code == 200
    create_payload = completed_job.json()
    assert create_payload["status"] == "completed"
    assert create_payload["gameSlug"]
    assert create_payload["playUrl"] == f"/play/{create_payload['gameSlug']}"

    projects = client.get("/create/projects", headers={"Authorization": f"Bearer {token}"})
    assert projects.status_code == 200
    assert any(project["projectId"] == create_payload["projectId"] for project in projects.json())

    project_detail = client.get(f"/create/projects/{create_payload['projectId']}", headers={"Authorization": f"Bearer {token}"})
    assert project_detail.status_code == 200
    assert project_detail.json()["projectId"] == create_payload["projectId"]

    run_detail = client.get(f"/create/runs/{create_payload['runId']}", headers={"Authorization": f"Bearer {token}"})
    assert run_detail.status_code == 200
    assert run_detail.json()["status"] == "completed"
    assert run_detail.json()["logObjectKey"].endswith("/run-log.jsonl")
    assert run_detail.json()["summary"]["promptTemplate"]["name"] == "yahaha-create-game"

    run_steps = client.get(f"/create/runs/{create_payload['runId']}/steps", headers={"Authorization": f"Bearer {token}"})
    assert run_steps.status_code == 200
    step_stages = [step["stage"] for step in run_steps.json()]
    assert "run_created" in step_stages
    assert "prompt_rendered" in step_stages
    assert "run_completed" in step_stages

    event_stream = client.get(f"/create/runs/{create_payload['runId']}/events", headers={"Authorization": f"Bearer {token}"})
    assert event_stream.status_code == 200
    assert "event: done" in event_stream.text

    agent_state = client.get(f"/create/jobs/{create_payload['id']}/agent-state", headers={"Authorization": f"Bearer {token}"})
    assert agent_state.status_code == 200
    assert agent_state.json()["run"]["runId"] == create_payload["runId"]

    missing_project_opt = client.post(
        "/create/jobs",
        json={"prompt": "make it faster", "files": [], "agentMode": "opt", "createType": "opt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing_project_opt.status_code == 409
    assert missing_project_opt.json()["detail"]["code"] == "PROJECT_ID_REQUIRED"

    opt_job = client.post(
        "/create/jobs",
        json={
            "prompt": "make it faster",
            "files": [],
            "agentMode": "opt",
            "createType": "opt",
            "projectId": create_payload["projectId"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert opt_job.status_code == 202
    started_opt_payload = opt_job.json()
    opt_job_final = client.get(f"/create/jobs/{started_opt_payload['id']}", headers={"Authorization": f"Bearer {token}"})
    assert opt_job_final.status_code == 200
    opt_payload = opt_job_final.json()
    assert opt_payload["projectId"] == create_payload["projectId"]
    assert opt_payload["runId"] != create_payload["runId"]
    assert opt_payload["createType"] == "opt"

    recent_game = client.get("/create/recent-game", headers={"Authorization": f"Bearer {token}"})
    assert recent_game.status_code == 200
    assert recent_game.json()["gameSlug"] == opt_payload["gameSlug"]

    generated_manifest = client.get(f"/play/{opt_payload['gameSlug']}/manifest")
    assert generated_manifest.status_code == 200
    assert generated_manifest.json()["runtime"] == "iframe-srcdoc"
    assert generated_manifest.json()["documentUrl"].endswith(f"/play/{opt_payload['gameSlug']}/document")
    assert generated_manifest.json()["assets"]

    generated_document = client.get(f"/play/{opt_payload['gameSlug']}/document")
    assert generated_document.status_code == 200
    assert "requestAnimationFrame" in generated_document.text
    assert "yahaha-game" in generated_document.text
    assert "AGENT_MODE" in generated_document.text
    assert "requestPointerLock" not in generated_document.text
    assert "preventDefault" in generated_document.text

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
