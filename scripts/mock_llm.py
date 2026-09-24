"""Local mock of an OpenAI-compatible /responses endpoint for end-to-end stack tests.

Started only with `docker compose --profile test up`. It distinguishes worker prompts:
- plan preview requests  -> a JSON plan
- decentralized requests -> three JSON candidates
- everything else        -> a self-contained HTML5 game
Usage must be reported consistently (input + output == total) or LlmClient rejects it.
"""
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
        if not self.path.endswith("/responses"):
            self._reply({"error": "unsupported path"}, 404)
            return
        if "ONLY JSON object with plan" in raw:
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
