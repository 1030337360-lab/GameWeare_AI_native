"""Local mock of OpenAI-compatible endpoints for end-to-end stack tests.

Started only with `docker compose --profile test up`. Two protocols are served:
- /responses      (legacy engine): distinguishes worker prompts by content
- /chat/completions (AgentScope engine): multi-turn tool-call state machine that
  mirrors the harness tools todo_write / write_file / validate_game_html /
  deliver_artifact / agent_spawn.
Usage must be reported consistently (input + output == total) or clients reject it.
"""
import itertools
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

GAME_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Mock Runner</title>
<style>body{margin:0;background:#111;color:#eee;font-family:monospace}canvas{display:block}</style>
</head>
<body>
<canvas id="stage" width="480" height="270"></canvas>
<p id="score">score 0</p>
<script>
const canvas = document.getElementById('stage');
const ctx = canvas.getContext('2d');
let x = 20, score = 0;
document.addEventListener('keydown', function (event) {
  if (event.key === 'ArrowRight') x = Math.min(460, x + 24);
  if (event.key === 'ArrowLeft') x = Math.max(0, x - 24);
});
function loop() {
  score += 1;
  ctx.fillStyle = '#16213e';
  ctx.fillRect(0, 0, 480, 270);
  ctx.fillStyle = '#0f3460';
  ctx.fillRect(0, 240, 480, 30);
  ctx.fillStyle = '#e94560';
  ctx.fillRect(x, 214, 20, 26);
  document.getElementById('score').textContent = 'score ' + score;
  requestAnimationFrame(loop);
}
loop();
</script>
</body>
</html>"""

PLAN = json.dumps({
    "plan": [
        {"id": "s1", "title": "Core loop", "goal": "Render the scene every frame",
         "toolFamily": "canvas", "expectedOutput": "animation loop", "acceptanceCheckRefs": ["c1"]},
        {"id": "s2", "title": "Controls", "goal": "Move the player with arrow keys",
         "toolFamily": "input", "expectedOutput": "responsive controls", "acceptanceCheckRefs": ["c2"]},
        {"id": "s3", "title": "Scoring", "goal": "Increase the score over time",
         "toolFamily": "dom", "expectedOutput": "visible score", "acceptanceCheckRefs": ["c3"]},
    ],
    "risks": ["Low-end device performance", "Keyboard focus inside the sandboxed iframe"],
    "acceptanceChecks": [
        {"id": "c1", "description": "Canvas repaints continuously", "type": "manual", "severity": "high"},
        {"id": "c2", "description": "Player moves left and right", "type": "manual", "severity": "high"},
        {"id": "c3", "description": "Score counter increases", "type": "manual", "severity": "medium"},
    ],
})

COVER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900"><rect width="1200" height="900" fill="#102030"/><circle cx="880" cy="410" r="210" fill="#c7f36b"/><text x="120" y="450" fill="#ffffff" font-size="64" font-family="Arial">Mock Runner</text></svg>"""

CANDIDATES = json.dumps({"candidates": [
    {"candidateId": "neon-runner", "title": "Neon Runner", "conceptSummary": "Fast endless runner",
     "expertRole": "Gameplay", "expertDomain": "Arcade", "expertIntro": "Speed is the core emotion.",
     "styleTags": ["neon", "fast"],
     "staticHtml": "<!doctype html><html><body style='background:#111;color:#0ff;font-family:monospace'><h1>Neon Runner</h1><p>dash forward</p></body></html>"},
    {"candidateId": "pixel-dungeon", "title": "Pixel Dungeon", "conceptSummary": "Tile crawler with loot",
     "expertRole": "Systems", "expertDomain": "RPG", "expertIntro": "Depth through item synergies.",
     "styleTags": ["pixel", "roguelite"],
     "staticHtml": "<!doctype html><html><body style='background:#1a1a2e;color:#e94560;font-family:monospace'><h1>Pixel Dungeon</h1><p>descend</p></body></html>"},
    {"candidateId": "space-shooter", "title": "Space Shooter", "conceptSummary": "Wave-based space shooter",
     "expertRole": "Combat", "expertDomain": "Action", "expertIntro": "Readable bullets, fair patterns.",
     "styleTags": ["space", "shooter"],
     "staticHtml": "<!doctype html><html><body style='background:#0f0f1a;color:#4cc9f0;font-family:monospace'><h1>Space Shooter</h1><p>hold the line</p></body></html>"},
]})

CALL_IDS = itertools.count(1)


def _tool_call(name, arguments):
    return {"id": "call_%d" % next(CALL_IDS), "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)}}


def _chat_response(message, finish_reason, prompt_tokens=50, completion_tokens=50):
    return {
        "id": "chatcmpl-%d" % next(CALL_IDS),
        "object": "chat.completion",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                  "total_tokens": prompt_tokens + completion_tokens},
    }


def _text_reply(content):
    return _chat_response({"role": "assistant", "content": content}, "stop")


def _tools_reply(calls):
    return _chat_response({"role": "assistant", "content": None, "tool_calls": calls}, "tool_calls")


def handle_chat_completions(body):
    """State machine over the request messages.

    Classification uses the exact system-prompt sentences produced by
    AgentScopeCreateEngine.systemPrompt, so the mock stays in sync with the app.
    """
    messages = body.get("messages") or []
    flat = json.dumps(messages)

    def tool_names():
        names = []
        for message in messages:
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    names.append(call.get("function", {}).get("name"))
        return names

    def spawned_ids():
        ids = []
        for message in messages:
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    if call.get("function", {}).get("name") == "agent_spawn":
                        try:
                            ids.append(json.loads(call["function"]["arguments"]).get("agentId"))
                        except Exception:
                            pass
        return ids

    if "Gameweare cover artist" in flat:
        names = tool_names()
        writes = names.count("write_file")
        validations = names.count("validate_cover_svg")
        tool_feedback = " ".join(str(m.get("content")) for m in messages if m.get("role") == "tool")
        if "const ctx = canvas.getContext('2d')" not in flat or "requestAnimationFrame(loop)" not in flat:
            return _text_reply("Complete game source was not preloaded for the cover stage.")
        if "todo_write" not in names:
            return _tools_reply([_tool_call("todo_write", {"todos": [
                {"content": "Read the complete game source", "status": "in_progress"},
                {"content": "Draw and validate cover.svg", "status": "pending"},
                {"content": "Deliver the verified cover", "status": "pending"},
            ]})])
        if writes == 0:
            return _tools_reply([_tool_call("write_file", {"path": "cover.svg",
                "content": "<svg><script>not allowed</script></svg>"})])
        if validations == 0:
            return _tools_reply([_tool_call("validate_cover_svg", {"filePath": "cover.svg"})])
        if "FAIL: SVG parse or safety check failed" not in tool_feedback:
            return _text_reply("Specific SVG validation feedback was not returned to the cover agent.")
        if "edit_file" not in names:
            return _tools_reply([_tool_call("edit_file", {"path": "cover.svg",
                "old_string": "<svg><script>not allowed</script></svg>",
                "new_string": COVER_SVG})])
        if validations == 1:
            return _tools_reply([_tool_call("validate_cover_svg", {"filePath": "cover.svg"})])
        if "PASS: cover.svg" not in tool_feedback:
            return _text_reply("The edited SVG did not pass the cover validator.")
        if "deliver_artifact" not in names:
            return _tools_reply([_tool_call("deliver_artifact",
                {"filePath": "cover.svg", "fileName": "cover.svg"})])
        return _text_reply("Validated cover.svg was delivered.")

    if "Delegate planning with agent_spawn to planner" in flat:
        if "planner" in spawned_ids():
            return _text_reply(PLAN)
        return _tools_reply([_tool_call("agent_spawn",
                                        {"agentId": "planner", "task": "Plan the requested game."})])
    if "Delegate three distinct concepts" in flat:
        spawned = [i for i in spawned_ids() if i and i.startswith("concept-")]
        if len(spawned) >= 3:
            return _text_reply(CANDIDATES)
        calls = [_tool_call("agent_spawn",
                            {"agentId": "concept-%d" % n, "task": "Design concept %d." % n})
                 for n in (1, 2, 3) if ("concept-%d" % n) not in spawned]
        return _tools_reply(calls)
    if "You create a self-contained single-file HTML5 browser game" in flat:
        names = tool_names()
        if "todo_write" not in names:
            return _tools_reply([_tool_call("todo_write", {"todos": [
                {"content": "Implement the HTML game", "status": "in_progress"},
                {"content": "Validate index.html", "status": "pending"},
                {"content": "Deliver the verified game", "status": "pending"},
            ]})])
        if "execute" not in names:
            return _tools_reply([_tool_call("execute", {"command": "if [ -e 'index.html' ]; then echo 'EXISTS'; exit 1; fi; mkdir -p \"$(dirname 'index.html')\" 2>&1"})])
        if "write_file" not in names:
            return _tools_reply([_tool_call("write_file", {"path": "index.html", "content": GAME_HTML})])
        if "validate_game_html" not in names:
            return _tools_reply([_tool_call("validate_game_html", {"filePath": "index.html"})])
        if "deliver_artifact" not in names:
            return _tools_reply([_tool_call("deliver_artifact",
                                            {"filePath": "index.html", "fileName": "index.html"})])
        return _text_reply("The game was written to the workspace and delivered as index.html.")
    # Subagent sessions (planner / concept-N) get a plain contribution.
    return _text_reply("Mock subagent contribution: concept notes and acceptance checks.")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._reply({"status": "ok"})
        else:
            self._reply({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        if self.path.endswith("/chat/completions"):
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                self._reply({"error": "invalid json"}, 400)
                return
            self._reply(handle_chat_completions(body))
            return
        if not self.path.endswith("/responses"):
            self._reply({"error": "unsupported path"}, 404)
            return
        if "Gameweare cover artist" in raw:
            text = COVER_SVG
        elif "ONLY JSON object with plan" in raw:
            text = PLAN
        elif "ONLY JSON object with candidates" in raw:
            text = CANDIDATES
        else:
            text = GAME_HTML
        input_tokens, output_tokens = 64, 512
        self._reply({
            "output_text": text,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        })

    def log_message(self, fmt, *args):
        print("mock-llm:", fmt % args, flush=True)


if __name__ == "__main__":
    print("mock-llm listening on :8080", flush=True)
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
