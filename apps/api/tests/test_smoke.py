from pathlib import Path
import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["CREATE_STATIC_GENERATION"] = "true"

from tests.support.integration import configure_test_environment, isolated_integration_test

configure_test_environment()

from app.main import app
from app.config import get_settings
from app.database import db_connection
from app.schemas import LLMTestResult
from app.services import create_service
from app.services.maintenance_service import bootstrap_maintainer_account
from app.services.play_stats_service import flush_pending_play_counts


client = TestClient(app)


def run() -> None:
    assert client.get("/health").json() == {"status": "ok"}

    public_ai_config = client.get("/create/ai-config")
    assert public_ai_config.status_code == 200
    assert public_ai_config.json() == {"authenticated": False, "configured": False, "staticGeneration": True}

    games = client.get("/games")
    assert games.status_code == 200
    assert len(games.json()) >= 3
    first_game = games.json()[0]
    assert "likes" in first_game
    assert "favorites" in first_game
    assert "likedByMe" in first_game
    assert "favoritedByMe" in first_game

    search_games = client.get("/games?q=astro")
    assert search_games.status_code == 200
    assert any(game["id"] == "astro-ludo" for game in search_games.json())

    tags = client.get("/games/tags")
    assert tags.status_code == 200
    assert "Arcade" in tags.json()

    filtered_games = client.get("/games?tag=Arcade")
    assert filtered_games.status_code == 200
    assert filtered_games.json()
    assert all("Arcade" in game["tags"] for game in filtered_games.json())

    manifest = client.get("/play/astro-ludo/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["bundleUrl"].endswith("/bundles/games/astro-ludo/index.html")

    play_event = client.post("/events/play", json={"gameId": "astro-ludo", "event": "game_view"})
    assert play_event.status_code == 200

    anonymous_id = str(uuid4())
    before_play = client.get("/games/astro-ludo")
    assert before_play.status_code == 200
    before_count = before_play.json()["plays"]
    with db_connection() as connection:
        before_db_count = connection.execute("SELECT plays_count FROM games WHERE slug = 'astro-ludo'").fetchone()["plays_count"]
    first_start = client.post("/events/play", json={"gameId": "astro-ludo", "event": "game_start", "anonymousId": anonymous_id})
    assert first_start.status_code == 200
    assert first_start.json()["counted"] is True
    duplicate_start = client.post("/events/play", json={"gameId": "astro-ludo", "event": "game_start", "anonymousId": anonymous_id})
    assert duplicate_start.status_code == 200
    assert duplicate_start.json()["counted"] is False
    after_play = client.get("/games/astro-ludo")
    assert after_play.status_code == 200
    assert after_play.json()["plays"] == before_count + 1
    with db_connection() as connection:
        pending_db_count = connection.execute("SELECT plays_count FROM games WHERE slug = 'astro-ludo'").fetchone()["plays_count"]
    flushed = flush_pending_play_counts()
    with db_connection() as connection:
        after_db_count = connection.execute("SELECT plays_count FROM games WHERE slug = 'astro-ludo'").fetchone()["plays_count"]
    assert pending_db_count >= before_db_count
    assert after_db_count >= before_db_count
    assert sum(flushed.values()) >= 0

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

    user_play = client.post(
        "/events/play",
        json={"gameId": "astro-ludo", "event": "game_start"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert user_play.status_code == 200

    like = client.put("/games/astro-ludo/like", headers={"Authorization": f"Bearer {token}"})
    assert like.status_code == 200
    assert like.json()["likedByMe"] is True
    like_again = client.put("/games/astro-ludo/like", headers={"Authorization": f"Bearer {token}"})
    assert like_again.status_code == 200
    assert like_again.json()["likes"] == like.json()["likes"]
    favorite = client.put("/games/astro-ludo/favorite", headers={"Authorization": f"Bearer {token}"})
    assert favorite.status_code == 200
    assert favorite.json()["favoritedByMe"] is True
    authed_detail = client.get("/games/astro-ludo", headers={"Authorization": f"Bearer {token}"})
    assert authed_detail.status_code == 200
    assert authed_detail.json()["likedByMe"] is True
    assert authed_detail.json()["favoritedByMe"] is True
    unlike = client.delete("/games/astro-ludo/like", headers={"Authorization": f"Bearer {token}"})
    assert unlike.status_code == 200
    assert unlike.json()["likedByMe"] is False
    unfavorite = client.delete("/games/astro-ludo/favorite", headers={"Authorization": f"Bearer {token}"})
    assert unfavorite.status_code == 200
    assert unfavorite.json()["favoritedByMe"] is False

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
    assert "baseUrl" not in ai_config_payload
    assert "model" not in ai_config_payload
    assert "apiKey" not in ai_config_payload

    saved_config_state = client.get("/create/ai-config", headers={"Authorization": f"Bearer {token}"})
    assert saved_config_state.status_code == 200
    assert saved_config_state.json()["configured"] is True
    assert "baseUrl" not in saved_config_state.json()
    assert "model" not in saved_config_state.json()

    relogin = client.post("/auth/login", json={"email": email, "password": "password123"})
    assert relogin.status_code == 200
    relogin_token = relogin.json()["accessToken"]
    relogin_config_state = client.get("/create/ai-config", headers={"Authorization": f"Bearer {relogin_token}"})
    assert relogin_config_state.status_code == 200
    assert relogin_config_state.json()["configured"] is True
    assert "baseUrl" not in relogin_config_state.json()
    assert "model" not in relogin_config_state.json()

    original_test_llm_config = create_service.test_llm_config
    try:
        create_service.test_llm_config = lambda **kwargs: LLMTestResult(  # type: ignore[assignment]
            ok=True,
            code="ok",
            message="Saved configuration works.",
            details={"model": kwargs["model"]},
        )
        saved_config_test = client.post("/create/ai-config/test", headers={"Authorization": f"Bearer {relogin_token}"})
        assert saved_config_test.status_code == 200
        assert saved_config_test.json()["ok"] is True
    finally:
        create_service.test_llm_config = original_test_llm_config  # type: ignore[assignment]

    create_job = client.post(
        "/create/jobs",
        json={"prompt": "collect bright stars with pointer controls", "files": [], "agentMode": "chat", "createType": "init"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_job.status_code == 202
    create_payload = create_job.json()
    assert create_payload["status"] == "planning"
    assert create_payload["agentMode"] == "chat"
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
    assert create_payload["publishStatus"] == "draft"
    assert create_payload["visibility"] == "private"
    assert create_payload["versionNo"] == 1

    draft_manifest = client.get(f"/play/{create_payload['gameSlug']}/manifest")
    assert draft_manifest.status_code == 404

    draft_preview = client.get(f"/create/projects/{create_payload['projectId']}/preview", headers={"Authorization": f"Bearer {token}"})
    assert draft_preview.status_code == 200
    assert draft_preview.json()["projectId"] == create_payload["projectId"]
    assert draft_preview.json()["versionNo"] == 1
    assert "requestAnimationFrame" in draft_preview.json()["html"]

    projects = client.get("/create/projects", headers={"Authorization": f"Bearer {token}"})
    assert projects.status_code == 200
    draft_project = next(project for project in projects.json() if project["projectId"] == create_payload["projectId"])
    assert draft_project["publishStatus"] == "draft"
    assert draft_project["currentVersionNo"] == 1

    project_detail = client.get(f"/create/projects/{create_payload['projectId']}", headers={"Authorization": f"Bearer {token}"})
    assert project_detail.status_code == 200
    assert project_detail.json()["projectId"] == create_payload["projectId"]
    assert project_detail.json()["publishStatus"] == "draft"

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
    assert "safety_scan" in step_stages
    assert "run_completed" in step_stages

    publish_response = client.post(f"/create/jobs/{create_payload['id']}/publish", headers={"Authorization": f"Bearer {token}"})
    assert publish_response.status_code == 200
    create_payload = publish_response.json()
    assert create_payload["publishStatus"] == "published"
    assert create_payload["visibility"] == "public"

    generated_versions = client.get(f"/games/{create_payload['gameSlug']}/versions", headers={"Authorization": f"Bearer {token}"})
    assert generated_versions.status_code == 200
    assert generated_versions.json()[0]["versionNo"] == 1
    assert generated_versions.json()[0]["current"] is True
    assert generated_versions.json()[0]["safetyStatus"] == "passed"

    remix_response = client.post(f"/games/{create_payload['gameSlug']}/remix", headers={"Authorization": f"Bearer {token}"})
    assert remix_response.status_code == 200
    remix_payload = remix_response.json()
    assert remix_payload["gameSlug"].startswith("remix-")
    assert remix_payload["status"] == "draft"

    event_stream = client.get(f"/create/runs/{create_payload['runId']}/events", headers={"Authorization": f"Bearer {token}"})
    assert event_stream.status_code == 200
    assert "event: done" in event_stream.text

    agent_state = client.get(f"/create/jobs/{create_payload['id']}/agent-state", headers={"Authorization": f"Bearer {token}"})
    assert agent_state.status_code == 200
    assert agent_state.json()["run"]["runId"] == create_payload["runId"]

    profile_activity = client.get("/profile/activity", headers={"Authorization": f"Bearer {token}"})
    assert profile_activity.status_code == 200
    profile_payload = profile_activity.json()
    assert profile_payload["recentPlays"]
    assert profile_payload["recentPlays"][0]["game"]["id"] == "astro-ludo"
    assert any(project["projectId"] == create_payload["projectId"] for project in profile_payload["projects"])

    profile_project = client.get(f"/profile/projects/{create_payload['projectId']}", headers={"Authorization": f"Bearer {token}"})
    assert profile_project.status_code == 200
    project_payload = profile_project.json()
    assert project_payload["project"]["projectId"] == create_payload["projectId"]
    assert project_payload["game"]["id"] == create_payload["gameSlug"]
    assert project_payload["runs"]
    assert project_payload["runs"][0]["promptSummary"]
    assert "llmFull" in project_payload["runs"][0]
    assert "steps" in project_payload["runs"][0]
    assert project_payload["runs"][0]["steps"]
    assert project_payload["runs"][0]["steps"] == sorted(project_payload["runs"][0]["steps"], key=lambda step: step["stepNo"])
    step_types = {step["recordType"] for step in project_payload["runs"][0]["steps"]}
    assert step_types & {"conversation", "llm", "lifecycle"}

    with db_connection() as connection:
        connection.execute(
            """
INSERT INTO create_run_steps (run_id, step_no, stage, status, input_summary, output_summary, metrics)
VALUES (%s, 900, 'llm_call', 'succeeded', %s, %s, %s)
ON CONFLICT (run_id, step_no) DO UPDATE SET
  input_summary = EXCLUDED.input_summary,
  output_summary = EXCLUDED.output_summary,
  metrics = EXCLUDED.metrics
""",
            (
                create_payload["runId"],
                "Authorization: Bearer should-not-leak api_key=should-not-leak",
                "LLM returned data:image/png;base64,AAAA and token=should-not-leak",
                Jsonb(
                    {
                        "outputTokens": 123,
                        "promptEnglishWords": 12,
                        "promptChineseChars": 3,
                        "api_key": "should-not-leak",
                        "image_url": "data:image/png;base64,AAAA",
                    }
                ),
            ),
        )
        connection.execute(
            """
INSERT INTO create_run_steps (run_id, step_no, stage, status, input_summary, output_summary, metrics)
VALUES (%s, 901, 'tool_call', 'failed', %s, %s, %s)
ON CONFLICT (run_id, step_no) DO UPDATE SET
  input_summary = EXCLUDED.input_summary,
  output_summary = EXCLUDED.output_summary,
  metrics = EXCLUDED.metrics
""",
            (
                create_payload["runId"],
                "write_file request password=should-not-leak",
                "tool failed with secret=should-not-leak",
                Jsonb(
                    {
                        "toolName": "write_file",
                        "files": ["games/index.html"],
                        "ok": False,
                        "error": {"message": "Authorization: Bearer should-not-leak"},
                    }
                ),
            ),
        )

    profile_project = client.get(f"/profile/projects/{create_payload['projectId']}", headers={"Authorization": f"Bearer {token}"})
    assert profile_project.status_code == 200
    redacted_payload = profile_project.json()
    redacted_text = str(redacted_payload)
    assert "should-not-leak" not in redacted_text
    assert "data:image/png;base64" not in redacted_text
    target_run = next(run for run in redacted_payload["runs"] if run["runId"] == create_payload["runId"])
    redacted_steps = target_run["steps"]
    assert redacted_steps == sorted(redacted_steps, key=lambda step: step["stepNo"])
    assert any(step["recordType"] == "llm" and step["metrics"]["outputTokens"] == 123 for step in redacted_steps)
    assert any(step["recordType"] == "tool" and step["metrics"]["toolName"] == "write_file" for step in redacted_steps)

    non_admin_maintenance = client.get("/maintenance/overview", headers={"Authorization": f"Bearer {token}"})
    assert non_admin_maintenance.status_code == 403

    settings = get_settings()
    assert settings.maintainer_email
    assert settings.maintainer_password
    bootstrap_maintainer_account()
    admin_email = settings.maintainer_email
    admin_login = client.post("/auth/login", json={"email": admin_email, "password": "password123"})
    if admin_login.status_code != 200:
        admin_login = client.post("/auth/login", json={"email": admin_email, "password": settings.maintainer_password})
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["accessToken"]
    admin_user_id = admin_login.json()["user"]["id"]

    maintenance_overview = client.get("/maintenance/overview", headers={"Authorization": f"Bearer {admin_token}"})
    assert maintenance_overview.status_code == 200
    assert "jobCounts" in maintenance_overview.json()
    assert "assetsTotal" in maintenance_overview.json()

    maintenance_jobs = client.get("/maintenance/jobs?limit=5", headers={"Authorization": f"Bearer {admin_token}"})
    assert maintenance_jobs.status_code == 200
    assert any(job["id"] == create_payload["id"] for job in maintenance_jobs.json())
    review_job = client.post(
        f"/maintenance/jobs/{create_payload['id']}/mark-reviewed",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert review_job.status_code == 200
    assert review_job.json()["targetType"] == "job"

    with db_connection() as connection:
        failed_run = connection.execute(
            """
INSERT INTO create_runs (
  task_id, project_id, user_id, job_id, create_type, agent_mode, status, log_object_key, completed_at
)
VALUES (gen_random_uuid(), %s, %s, %s, 'opt', 'react', 'failed', %s, now())
RETURNING id
""",
            (create_payload["projectId"], admin_user_id, create_payload["id"], f"agent-runs/{uuid4().hex}/run-log.jsonl"),
        ).fetchone()
        connection.execute(
            "UPDATE generation_jobs SET status = 'failed', error_code = 'SMOKE_FAILED', error_message = 'Smoke failed create run' WHERE id = %s",
            (create_payload["id"],),
        )
        connection.execute(
            """
INSERT INTO create_run_steps (run_id, step_no, stage, status, input_summary, output_summary, metrics)
VALUES
  (%s, 1, 'llm_call', 'succeeded', 'prompt prefix', 'model output', %s),
  (%s, 2, 'tool_call', 'failed', 'write file', 'tool error', %s)
""",
            (
                failed_run["id"],
                Jsonb({"outputTokens": 77, "promptEnglishWords": 9, "promptChineseChars": 2}),
                failed_run["id"],
                Jsonb({"toolName": "write_file", "files": ["index.html"], "ok": False, "error": {"message": "failed"}}),
            ),
        )
    failed_runs = client.get("/maintenance/create-runs/failed?limit=5", headers={"Authorization": f"Bearer {admin_token}"})
    assert failed_runs.status_code == 200
    failed_payload = failed_runs.json()
    target_failed_run = next(run for run in failed_payload if run["runId"] == str(failed_run["id"]))
    assert target_failed_run["createType"] == "opt"
    assert target_failed_run["agentMode"] == "react"
    assert target_failed_run["totalOutputTokens"] == 77
    assert len(target_failed_run["steps"]) == 2
    assert target_failed_run["steps"][0]["outputTokens"] == 77
    retry_failed = client.post(f"/maintenance/jobs/{create_payload['id']}/retry", headers={"Authorization": f"Bearer {admin_token}"})
    assert retry_failed.status_code == 200
    retry_payload = retry_failed.json()
    assert retry_payload["status"] == "planning"
    assert retry_payload["createType"] == "init"
    assert retry_payload["agentMode"] == "chat"
    retry_final = client.get(f"/create/jobs/{retry_payload['id']}", headers={"Authorization": f"Bearer {token}"})
    assert retry_final.status_code == 200
    with db_connection() as connection:
        connection.execute(
            "UPDATE generation_jobs SET status = 'completed', error_code = NULL, error_message = NULL WHERE id = %s",
            (create_payload["id"],),
        )

    maintenance_games = client.get("/maintenance/games?q=astro-ludo", headers={"Authorization": f"Bearer {admin_token}"})
    assert maintenance_games.status_code == 200
    assert maintenance_games.json()
    managed_game = maintenance_games.json()[0]
    patch_game = client.patch(
        f"/maintenance/games/{managed_game['id']}",
        json={"visibility": "unlisted"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert patch_game.status_code == 200
    assert patch_game.json()["visibility"] == "unlisted"
    client.patch(
        f"/maintenance/games/{managed_game['id']}",
        json={"visibility": "public"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    moderate_game = client.post(
        f"/maintenance/games/{managed_game['id']}/moderate",
        json={"status": "approved", "reason": "Smoke reviewed"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert moderate_game.status_code == 200
    assert moderate_game.json()["targetType"] == "game"

    maintenance_assets = client.get("/maintenance/assets?limit=5", headers={"Authorization": f"Bearer {admin_token}"})
    assert maintenance_assets.status_code == 200
    assert isinstance(maintenance_assets.json(), list)
    with db_connection() as connection:
        disposable_asset = connection.execute(
            """
INSERT INTO assets (owner_id, kind, bucket, object_key, content_type, size_bytes)
VALUES (%s, 'upload', 'external', %s, 'text/plain', 4)
RETURNING id
""",
            (admin_user_id, f"maintenance-smoke/{uuid4().hex}.txt"),
        ).fetchone()
    delete_asset = client.delete(
        f"/maintenance/assets/{disposable_asset['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert delete_asset.status_code == 200
    assert delete_asset.json()["deleted"] is True

    missing_project_opt = client.post(
        "/create/jobs",
        json={"prompt": "make it faster", "files": [], "agentMode": "refine", "createType": "opt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing_project_opt.status_code == 409
    assert missing_project_opt.json()["detail"]["code"] == "PROJECT_ID_REQUIRED"

    opt_job = client.post(
        "/create/jobs",
        json={
            "prompt": "make it faster",
            "files": [],
            "agentMode": "refine",
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
    assert opt_payload["gameSlug"] == create_payload["gameSlug"]
    assert opt_payload["versionNo"] == 2
    assert opt_payload["publishStatus"] == "draft"

    opt_publish = client.post(f"/create/jobs/{opt_payload['id']}/publish", headers={"Authorization": f"Bearer {token}"})
    assert opt_publish.status_code == 200
    opt_payload = opt_publish.json()
    assert opt_payload["publishStatus"] == "published"

    recent_game = client.get("/create/recent-game", headers={"Authorization": f"Bearer {token}"})
    assert recent_game.status_code == 200
    assert recent_game.json()["gameSlug"] == opt_payload["gameSlug"]

    opt_versions = client.get(f"/games/{opt_payload['gameSlug']}/versions", headers={"Authorization": f"Bearer {token}"})
    assert opt_versions.status_code == 200
    assert [version["versionNo"] for version in opt_versions.json()] == [2, 1]
    assert opt_versions.json()[0]["current"] is True

    opt_job_3 = client.post(
        "/create/jobs",
        json={
            "prompt": "add a faster bonus round",
            "files": [],
            "agentMode": "refine",
            "createType": "opt",
            "projectId": create_payload["projectId"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert opt_job_3.status_code == 202
    opt_payload_3 = client.get(f"/create/jobs/{opt_job_3.json()['id']}", headers={"Authorization": f"Bearer {token}"}).json()
    assert opt_payload_3["versionNo"] == 3
    assert opt_payload_3["publishStatus"] == "draft"
    opt_draft_preview = client.get(f"/create/projects/{create_payload['projectId']}/preview", headers={"Authorization": f"Bearer {token}"})
    assert opt_draft_preview.status_code == 200
    assert opt_draft_preview.json()["versionNo"] == 3
    assert "requestAnimationFrame" in opt_draft_preview.json()["html"]
    opt_publish_3 = client.post(f"/create/jobs/{opt_payload_3['id']}/publish", headers={"Authorization": f"Bearer {token}"})
    assert opt_publish_3.status_code == 200
    pruned_versions = client.get(f"/games/{opt_payload['gameSlug']}/versions", headers={"Authorization": f"Bearer {token}"})
    assert pruned_versions.status_code == 200
    assert [version["versionNo"] for version in pruned_versions.json()] == [3, 2]

    generated_manifest = client.get(f"/play/{opt_payload['gameSlug']}/manifest")
    assert generated_manifest.status_code == 200
    assert generated_manifest.json()["runtime"] == "iframe-srcdoc"
    assert generated_manifest.json()["sandbox"] == ["allow-scripts"]
    assert "allow-same-origin" not in generated_manifest.text
    assert generated_manifest.json()["documentUrl"].endswith(f"/play/{opt_payload['gameSlug']}/document")
    assert generated_manifest.json()["assets"]

    generated_document = client.get(f"/play/{opt_payload['gameSlug']}/document")
    assert generated_document.status_code == 200
    assert "requestAnimationFrame" in generated_document.text
    assert "yahaha-game" in generated_document.text
    assert "AGENT_MODE" in generated_document.text
    assert "requestPointerLock" not in generated_document.text
    assert "preventDefault" in generated_document.text

    other_register = client.post(
        "/auth/register",
        json={"email": f"other-{uuid4().hex[:8]}@yahaha.local", "password": "password123", "displayName": "Other User"},
    )
    assert other_register.status_code == 200
    other_token = other_register.json()["accessToken"]
    other_delete = client.delete(f"/games/{create_payload['gameSlug']}", headers={"Authorization": f"Bearer {other_token}"})
    assert other_delete.status_code == 404

    with db_connection() as connection:
        failed_project = connection.execute(
            """
INSERT INTO agent_projects (user_id, title, status)
SELECT id, 'Failed smoke create project', 'active'
FROM users
WHERE email = %s
RETURNING id
""",
            (email,),
        ).fetchone()
        failed_job = connection.execute(
            """
INSERT INTO generation_jobs (creator_id, prompt, input_payload, status, current_stage, started_at, completed_at, error_code, error_message)
SELECT id, 'failed smoke prompt', %s, 'failed', 'llm_generation', now(), now(), 'SMOKE_FAILED_PROJECT', 'Failed before game publish'
FROM users
WHERE email = %s
RETURNING id
""",
            (Jsonb({"projectId": str(failed_project["id"]), "agentMode": "react", "createType": "init"}), email),
        ).fetchone()
        failed_project_run = connection.execute(
            """
INSERT INTO create_runs (
  task_id, project_id, user_id, job_id, create_type, agent_mode, status, log_object_key, completed_at
)
SELECT gen_random_uuid(), %s, id, %s, 'init', 'react', 'failed', %s, now()
FROM users
WHERE email = %s
RETURNING id
""",
            (failed_project["id"], failed_job["id"], f"agent-runs/{uuid4().hex}/run-log.jsonl", email),
        ).fetchone()
        connection.execute(
            """
INSERT INTO create_run_steps (run_id, step_no, stage, status, input_summary, output_summary, metrics)
VALUES (%s, 1, 'run_failed', 'failed', 'Create generation failed.', 'Smoke failed before game publish.', %s)
""",
            (failed_project_run["id"], Jsonb({"errorCode": "SMOKE_FAILED_PROJECT"})),
        )
    failed_project_id = str(failed_project["id"])
    failed_run_id = str(failed_project_run["id"])
    failed_before_delete = client.get("/profile/activity", headers={"Authorization": f"Bearer {token}"})
    assert failed_before_delete.status_code == 200
    assert any(project["projectId"] == failed_project_id for project in failed_before_delete.json()["projects"])
    other_failed_delete = client.delete(f"/create/projects/{failed_project_id}", headers={"Authorization": f"Bearer {other_token}"})
    assert other_failed_delete.status_code == 404
    delete_failed_project = client.delete(f"/create/projects/{failed_project_id}", headers={"Authorization": f"Bearer {token}"})
    assert delete_failed_project.status_code == 200
    assert delete_failed_project.json()["projectId"] == failed_project_id
    assert delete_failed_project.json()["gameSlug"] is None
    assert delete_failed_project.json()["runLogsPreserved"] is True
    failed_after_delete = client.get("/profile/activity", headers={"Authorization": f"Bearer {token}"})
    assert failed_after_delete.status_code == 200
    assert all(project["projectId"] != failed_project_id for project in failed_after_delete.json()["projects"])
    failed_create_project_detail = client.get(f"/create/projects/{failed_project_id}", headers={"Authorization": f"Bearer {token}"})
    assert failed_create_project_detail.status_code == 404
    failed_profile_project_detail = client.get(f"/profile/projects/{failed_project_id}", headers={"Authorization": f"Bearer {token}"})
    assert failed_profile_project_detail.status_code == 404
    with db_connection() as connection:
        deleted_failed_project = connection.execute("SELECT status FROM agent_projects WHERE id = %s", (failed_project_id,)).fetchone()
        preserved_failed_run = connection.execute("SELECT count(*) AS count FROM create_runs WHERE id = %s", (failed_run_id,)).fetchone()
        preserved_failed_steps = connection.execute("SELECT count(*) AS count FROM create_run_steps WHERE run_id = %s", (failed_run_id,)).fetchone()
    assert deleted_failed_project["status"] == "deleted"
    assert preserved_failed_run["count"] == 1
    assert preserved_failed_steps["count"] == 1
    failed_runs_after_delete = client.get("/maintenance/create-runs/failed?limit=20", headers={"Authorization": f"Bearer {admin_token}"})
    assert failed_runs_after_delete.status_code == 200
    assert any(run["runId"] == failed_run_id for run in failed_runs_after_delete.json())

    delete_game = client.delete(f"/games/{create_payload['gameSlug']}", headers={"Authorization": f"Bearer {token}"})
    assert delete_game.status_code == 200
    assert delete_game.json()["deleted"] is True
    assert delete_game.json()["runLogsPreserved"] is True

    deleted_detail = client.get(f"/games/{create_payload['gameSlug']}", headers={"Authorization": f"Bearer {token}"})
    assert deleted_detail.status_code == 404
    deleted_manifest = client.get(f"/play/{create_payload['gameSlug']}/manifest")
    assert deleted_manifest.status_code == 404
    deleted_versions = client.get(f"/games/{create_payload['gameSlug']}/versions", headers={"Authorization": f"Bearer {token}"})
    assert deleted_versions.status_code == 404
    deleted_games = client.get("/games")
    assert all(game["id"] != create_payload["gameSlug"] for game in deleted_games.json())

    deleted_profile_activity = client.get("/profile/activity", headers={"Authorization": f"Bearer {token}"})
    assert deleted_profile_activity.status_code == 200
    deleted_project = next(project for project in deleted_profile_activity.json()["projects"] if project["projectId"] == create_payload["projectId"])
    assert deleted_project["status"] == "archived"
    assert deleted_project["gameSlug"] is None
    deleted_profile_project = client.get(f"/profile/projects/{create_payload['projectId']}", headers={"Authorization": f"Bearer {token}"})
    assert deleted_profile_project.status_code == 200
    deleted_project_payload = deleted_profile_project.json()
    assert deleted_project_payload["game"] is None
    assert deleted_project_payload["runs"]
    assert deleted_project_payload["runs"][0]["steps"]
    assert deleted_project_payload["runs"][0]["steps"] == sorted(deleted_project_payload["runs"][0]["steps"], key=lambda step: step["stepNo"])

    deleted_opt = client.post(
        "/create/jobs",
        json={
            "prompt": "try to optimize deleted game",
            "files": [],
            "agentMode": "refine",
            "createType": "opt",
            "projectId": create_payload["projectId"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted_opt.status_code == 404

    logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    logged_out_session = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert logged_out_session.status_code == 200
    assert logged_out_session.json()["authenticated"] is False

    google_start = client.get("/auth/google/start", follow_redirects=False)
    assert google_start.status_code in (302, 307)
    assert "oauth_error=google_not_configured" in google_start.headers["location"]


if __name__ == "__main__":
    with isolated_integration_test():
        run()
    print("api smoke checks passed")
