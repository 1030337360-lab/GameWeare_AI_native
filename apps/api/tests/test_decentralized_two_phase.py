from pathlib import Path
import json
import os
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["CREATE_STATIC_GENERATION"] = "false"

from tests.support.integration import configure_test_environment, isolated_integration_test

configure_test_environment()

from app.agents.decentralized.prompts import build_expert_payload, build_final_game_payload
from app.agents.graphs.llm_adapter import LLMGraphResult, build_llm_call_metrics
from app.main import app
from app.services import create_service


class DecentralizedFakeAdapter:
    def invoke(self, payload: dict) -> LLMGraphResult:
        payload_text = json.dumps(payload, ensure_ascii=False)
        if "Yahaha Decentralized Expert Factory" in payload_text:
            output = {
                "experts": [
                    {
                        "role": "Ceramic Toy Sculptor",
                        "domain": "character craft",
                        "selfIntroduction": "I shape playful worlds through clay, rounded silhouettes, glaze color, and tactile charm. I look for characters that feel collectible, friendly, and surprising, then turn the creator request into a visual toy-box direction with clear mood, pacing, and delightful physical details.",
                        "styleTags": ["toy", "tactile", "soft"],
                    },
                    {
                        "role": "Subway Signage Designer",
                        "domain": "urban wayfinding",
                        "selfIntroduction": "I design movement systems from signs, arrows, constraints, and crowded transit rhythm. I translate the creator request into clean routes, bold signals, strong contrast, and moments of decision so the game feels like navigating a living city map.",
                        "styleTags": ["urban", "graphic", "route"],
                    },
                    {
                        "role": "Stage Lighting Director",
                        "domain": "performance lighting",
                        "selfIntroduction": "I build emotion with darkness, beams, color temperature, silhouettes, and reveals. I use the creator request as a performance score, designing scenes that shift attention, create drama, and make every game moment feel staged and expressive.",
                        "styleTags": ["stage", "contrast", "dramatic"],
                    },
                ]
            }
        elif "Fixed Game Preview Expert rules" in payload_text:
            title = "Static Direction"
            output = {
                "title": title,
                "conceptSummary": "A non-playable static visual direction.",
                "styleTags": ["static", "preview"],
                "staticHtml": "<!doctype html><html><body><main style='height:100vh;background:#111;color:white;display:grid;place-items:center'><h1>Static Direction</h1></main></body></html>",
            }
        elif "Yahaha Decentralized Final Game Agent" in payload_text:
            output = {
                "type": "final",
                "output": {
                    "Finished": True,
                    "files": [
                        {
                            "path": "index.html",
                            "content": "<!doctype html><html><body><canvas id='game'></canvas><script>window.parent.postMessage({source:'yahaha-game',type:'game_ready'}, '*'); window.addEventListener('keydown', e => e.preventDefault()); requestAnimationFrame(()=>{});</script></body></html>",
                        }
                    ],
                    "cover": {"title": "Decentralized Arcade", "description": "A selected direction became playable.", "tags": ["decentralized"]},
                    "implementationSummary": "Playable iframe game generated from selected preview.",
                    "safetyNotes": ["No privileged APIs."],
                },
            }
        elif "Yahaha Decentralized Cover Agent" in payload_text:
            output = {
                "svg": "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='900'><rect width='1200' height='900' fill='#111827'/><text x='80' y='180' fill='white' font-size='90'>Decentralized Arcade</text></svg>",
                "mimeType": "image/svg+xml",
                "summary": "SVG cover.",
            }
        else:
            output = {}
        text = json.dumps(output, ensure_ascii=False)
        raw = {"output_text": text, "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}
        return LLMGraphResult(text=text, raw=raw, metrics=build_llm_call_metrics(payload, response_text=text, response_raw=raw))


def run() -> None:
    init_payload = build_expert_payload(model="test-model", user_request="make a racing game", input_assets=[])
    continue_context = [{"type": "existing_project_artifacts", "previousIndexHtmlPrefix": "<html>old racer</html>"}]
    continue_payload = build_expert_payload(
        model="test-model",
        user_request="make the road more dramatic",
        input_assets=[],
        previous_project_context=continue_context,
    )
    init_user = init_payload["input"][1]["content"][0]["text"]
    continue_user = continue_payload["input"][1]["content"][0]["text"]
    assert '"creationIntent": "init"' in init_user
    assert '"creationIntent": "continue"' in continue_user
    assert "previousIndexHtmlPrefix" in continue_user
    final_payload = build_final_game_payload(
        model="test-model",
        user_request="continue racer",
        input_assets=[],
        candidate={"candidateId": "candidate-1", "title": "Racer", "staticHtml": "<html>preview</html>"},
        workspace_boundary=".worktrees/create-demo",
        previous_project_context=continue_context,
    )
    final_user = final_payload["input"][1]["content"][0]["text"]
    assert '"creationIntent": "continue"' in final_user
    assert "final output contract remains identical to initial creation" in final_user

    create_service._make_graph_adapter = lambda ai_config: DecentralizedFakeAdapter()  # type: ignore[assignment]
    client = TestClient(app)
    email = f"decentralized-{uuid4().hex[:10]}@yahaha.local"
    register = client.post("/auth/register", json={"email": email, "password": "password123", "displayName": "Decentralized User"})
    assert register.status_code == 200
    token = register.json()["accessToken"]
    headers = {"Authorization": f"Bearer {token}"}
    ai_config = client.put(
        "/create/ai-config",
        json={"baseUrl": "https://api.example.test/v1", "model": "test-model", "apiKey": "test-key"},
        headers=headers,
    )
    assert ai_config.status_code == 200

    started = client.post(
        "/create/jobs",
        json={"prompt": "make a dreamy platform game", "files": [], "agentMode": "decentralized", "createType": "init"},
        headers=headers,
    )
    assert started.status_code == 202
    start_payload = started.json()
    assert start_payload["agentMode"] == "decentralized"
    assert start_payload["gameSlug"] is None

    previews = client.get(f"/create/runs/{start_payload['runId']}/decentralized-previews", headers=headers)
    assert previews.status_code == 200
    preview_payload = previews.json()
    assert len(preview_payload["candidates"]) == 3
    assert preview_payload["selectedCandidateId"] is None

    job_before_confirm = client.get(f"/create/jobs/{start_payload['id']}", headers=headers)
    assert job_before_confirm.status_code == 200
    assert job_before_confirm.json()["gameSlug"] is None

    first_candidate = preview_payload["candidates"][0]["candidateId"]
    selected = client.post(
        f"/create/runs/{start_payload['runId']}/decentralized-selection",
        json={"candidateId": first_candidate},
        headers=headers,
    )
    assert selected.status_code == 200
    assert selected.json()["selectedCandidateId"] == first_candidate

    confirmed = client.post(
        f"/create/runs/{start_payload['runId']}/decentralized-confirm",
        json={"decision": "accepted"},
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] in {"generating", "completed"}

    final_job = client.get(f"/create/jobs/{start_payload['id']}", headers=headers)
    assert final_job.status_code == 200
    final_payload = final_job.json()
    assert final_payload["status"] == "completed"
    assert final_payload["gameSlug"].startswith("decentralized-arcade-")

    steps = client.get(f"/create/runs/{start_payload['runId']}/steps", headers=headers)
    assert steps.status_code == 200
    stages = [step["stage"] for step in steps.json()]
    assert "decentralized_preview_ready" in stages
    assert "decentralized_candidate_selected" in stages
    assert "decentralized_confirmed" in stages
    assert "decentralized_final_llm_call" in stages
    assert "decentralized_cover_generated" in stages
    assert "run_completed" in stages

    draft_manifest = client.get(f"/play/{final_payload['gameSlug']}/manifest")
    assert draft_manifest.status_code == 404
    published = client.post(f"/create/jobs/{final_payload['id']}/publish", headers=headers)
    assert published.status_code == 200
    final_payload = published.json()
    manifest = client.get(f"/play/{final_payload['gameSlug']}/manifest")
    assert manifest.status_code == 200
    document = client.get(f"/play/{final_payload['gameSlug']}/document")
    assert document.status_code == 200
    assert "requestAnimationFrame" in document.text

    reject_job = client.post(
        "/create/jobs",
        json={"prompt": "make alternatives then reject", "files": [], "agentMode": "decentralized", "createType": "init"},
        headers=headers,
    )
    assert reject_job.status_code == 202
    reject_payload = reject_job.json()
    reject_previews = client.get(f"/create/runs/{reject_payload['runId']}/decentralized-previews", headers=headers)
    assert reject_previews.status_code == 200
    rejected = client.post(
        f"/create/runs/{reject_payload['runId']}/decentralized-confirm",
        json={"decision": "rejected"},
        headers=headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "canceled"
    rejected_steps = client.get(f"/create/runs/{reject_payload['runId']}/steps", headers=headers)
    assert "decentralized_rejected" in [step["stage"] for step in rejected_steps.json()]


if __name__ == "__main__":
    with isolated_integration_test():
        run()
    print("decentralized two-phase checks passed")
