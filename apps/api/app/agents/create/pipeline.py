from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import PurePosixPath
from typing import Any

AGENT_MODES = ("chat", "react", "plan", "refine", "centralized", "decentralized", "init", "opt")


@dataclass(frozen=True)
class AgentArtifact:
    filename: str
    content: bytes
    content_type: str
    kind: str
    purpose: str


@dataclass(frozen=True)
class AgentRunRecord:
    stage: str
    status: str
    input_summary: str
    output_summary: str
    log: dict


@dataclass(frozen=True)
class AgentPipelineResult:
    title: str
    description: str
    runtime: str
    entry_file: str
    artifacts: list[AgentArtifact]
    runs: list[AgentRunRecord]
    source: dict


def normalize_agent_mode(agent_mode: str | None) -> str:
    mode = (agent_mode or "chat").strip().lower()
    return mode if mode in AGENT_MODES else "chat"


def title_from_prompt(prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)
    if not words:
        return "Generated Arcade"
    return " ".join(words[:5]).title()[:80]


def build_static_game_html(title: str, game_slug: str, game_id: str, version_id: str, prompt: str, agent_mode: str) -> str:
    safe_title = json.dumps(title)
    safe_slug = json.dumps(game_slug)
    safe_game_id = json.dumps(game_id)
    safe_version_id = json.dumps(version_id)
    safe_prompt = json.dumps(prompt)
    safe_mode = json.dumps(agent_mode)
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <style>
      html, body {{
        margin: 0;
        width: 100%;
        height: 100%;
        overflow: hidden;
        background: #07080d;
        color: #f8fbff;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      canvas {{
        display: block;
        width: 100vw;
        height: 100vh;
        touch-action: none;
      }}
      .hud {{
        position: fixed;
        left: 18px;
        top: 16px;
        display: grid;
        gap: 6px;
        pointer-events: none;
        text-shadow: 0 2px 18px rgba(0,0,0,.55);
      }}
      .hud h1 {{
        margin: 0;
        font-size: clamp(22px, 5vw, 44px);
        line-height: 1;
      }}
      .hud p {{
        margin: 0;
        color: #c5d3ea;
        font-size: 14px;
      }}
      .start {{
        position: fixed;
        left: 50%;
        bottom: 26px;
        transform: translateX(-50%);
        border: 0;
        border-radius: 999px;
        padding: 12px 20px;
        font-weight: 900;
        background: #ffffff;
        color: #0d1118;
        box-shadow: 0 18px 60px rgba(0,0,0,.32);
      }}
    </style>
  </head>
  <body>
    <canvas id="game"></canvas>
    <section class="hud">
      <h1></h1>
      <p id="score">Score 0</p>
      <p>Mode: <span id="mode"></span> · Pointer or touch to steer. WASD / arrows also work.</p>
    </section>
    <button class="start" id="start">Start / Replay</button>
    <script>
      const GAME_ID = {safe_slug};
      const DB_GAME_ID = {safe_game_id};
      const VERSION_ID = {safe_version_id};
      const TITLE = {safe_title};
      const PROMPT = {safe_prompt};
      const AGENT_MODE = {safe_mode};
      const canvas = document.getElementById("game");
      const ctx = canvas.getContext("2d");
      const startButton = document.getElementById("start");
      const scoreLabel = document.getElementById("score");
      document.querySelector(".hud h1").textContent = TITLE;
      document.getElementById("mode").textContent = AGENT_MODE;

      let width = 0;
      let height = 0;
      let running = false;
      let lastTime = 0;
      let score = 0;
      let target = {{ x: 0, y: 0 }};
      let player = {{ x: 0, y: 0, radius: 18, vx: 0, vy: 0 }};
      let gems = [];
      const keys = new Set();

      function send(type, payload = {{}}) {{
        window.parent.postMessage({{
          source: "yahaha-game",
          type,
          gameId: GAME_ID,
          dbGameId: DB_GAME_ID,
          versionId: VERSION_ID,
          payload
        }}, "*");
      }}

      function resize() {{
        width = canvas.width = Math.max(320, window.innerWidth * window.devicePixelRatio);
        height = canvas.height = Math.max(240, window.innerHeight * window.devicePixelRatio);
        canvas.style.width = "100vw";
        canvas.style.height = "100vh";
        player.x = player.x || width / 2;
        player.y = player.y || height / 2;
        target.x = target.x || player.x;
        target.y = target.y || player.y;
      }}

      function spawnGems() {{
        gems = Array.from({{ length: 9 }}, (_, index) => ({{
          x: 60 + Math.random() * (width - 120),
          y: 90 + Math.random() * (height - 160),
          radius: 10 + (index % 3) * 4,
          hue: 165 + index * 18,
          alive: true
        }}));
      }}

      function reset() {{
        score = 0;
        player = {{ x: width / 2, y: height / 2, radius: 18, vx: 0, vy: 0 }};
        target = {{ x: player.x, y: player.y }};
        spawnGems();
        scoreLabel.textContent = "Score 0";
      }}

      function startGame() {{
        reset();
        running = true;
        lastTime = performance.now();
        startButton.textContent = "Replay";
        send("game_start", {{ prompt: PROMPT, agentMode: AGENT_MODE }});
        requestAnimationFrame(loop);
      }}

      function update(delta) {{
        let ax = (target.x - player.x) * 0.9;
        let ay = (target.y - player.y) * 0.9;
        if (keys.has("ArrowLeft") || keys.has("a")) ax -= 800;
        if (keys.has("ArrowRight") || keys.has("d")) ax += 800;
        if (keys.has("ArrowUp") || keys.has("w")) ay -= 800;
        if (keys.has("ArrowDown") || keys.has("s")) ay += 800;
        player.vx = (player.vx + ax * delta) * 0.88;
        player.vy = (player.vy + ay * delta) * 0.88;
        player.x = Math.min(width - player.radius, Math.max(player.radius, player.x + player.vx * delta));
        player.y = Math.min(height - player.radius, Math.max(player.radius, player.y + player.vy * delta));

        for (const gem of gems) {{
          if (!gem.alive) continue;
          const dx = gem.x - player.x;
          const dy = gem.y - player.y;
          if (Math.hypot(dx, dy) < player.radius + gem.radius) {{
            gem.alive = false;
            score += 10;
            scoreLabel.textContent = "Score " + score;
            send("game_score", {{ score }});
          }}
        }}
        if (gems.every((gem) => !gem.alive)) {{
          running = false;
          send("game_end", {{ score }});
        }}
      }}

      function render() {{
        const gradient = ctx.createLinearGradient(0, 0, width, height);
        gradient.addColorStop(0, "#111827");
        gradient.addColorStop(0.52, "#102033");
        gradient.addColorStop(1, "#050712");
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);

        ctx.save();
        ctx.globalAlpha = 0.22;
        ctx.strokeStyle = "#6ee7ff";
        for (let x = 0; x < width; x += 56 * window.devicePixelRatio) {{
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, height);
          ctx.stroke();
        }}
        for (let y = 0; y < height; y += 56 * window.devicePixelRatio) {{
          ctx.beginPath();
          ctx.moveTo(0, y);
          ctx.lineTo(width, y);
          ctx.stroke();
        }}
        ctx.restore();

        for (const gem of gems) {{
          if (!gem.alive) continue;
          ctx.beginPath();
          ctx.fillStyle = `hsl(${{gem.hue}}, 88%, 62%)`;
          ctx.shadowColor = ctx.fillStyle;
          ctx.shadowBlur = 22;
          ctx.arc(gem.x, gem.y, gem.radius * window.devicePixelRatio, 0, Math.PI * 2);
          ctx.fill();
        }}
        ctx.shadowBlur = 0;
        ctx.beginPath();
        ctx.fillStyle = "#ffffff";
        ctx.arc(player.x, player.y, player.radius * window.devicePixelRatio, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.strokeStyle = "#6ee7ff";
        ctx.lineWidth = 4;
        ctx.arc(player.x, player.y, (player.radius + 8) * window.devicePixelRatio, 0, Math.PI * 2);
        ctx.stroke();
      }}

      function loop(timestamp) {{
        if (!running) return;
        const delta = Math.min((timestamp - lastTime) / 1000, 0.033);
        lastTime = timestamp;
        update(delta);
        render();
        requestAnimationFrame(loop);
      }}

      function setPointer(event) {{
        const rect = canvas.getBoundingClientRect();
        target.x = (event.clientX - rect.left) * window.devicePixelRatio;
        target.y = (event.clientY - rect.top) * window.devicePixelRatio;
      }}

      window.addEventListener("resize", () => {{ resize(); render(); }});
      function isGameKey(key) {{
        return ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "Spacebar", "w", "a", "s", "d"].includes(key);
      }}

      window.addEventListener("keydown", (event) => {{
        if (isGameKey(event.key)) event.preventDefault();
        keys.add(event.key);
      }}, {{ passive: false }});
      window.addEventListener("keyup", (event) => {{
        if (isGameKey(event.key)) event.preventDefault();
        keys.delete(event.key);
      }}, {{ passive: false }});
      document.addEventListener("visibilitychange", () => {{
        if (document.hidden && running) send("game_pause");
        if (!document.hidden && running) send("game_resume");
      }});
      canvas.addEventListener("pointerdown", (event) => {{
        setPointer(event);
        if (!running) startGame();
      }});
      canvas.addEventListener("pointermove", setPointer);
      startButton.addEventListener("click", startGame);

      resize();
      reset();
      render();
      send("game_ready", {{ title: TITLE, agentMode: AGENT_MODE }});
    </script>
  </body>
</html>
"""


def build_cover_svg(title: str) -> bytes:
    safe_title = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900" viewBox="0 0 1200 900">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="#0f172a"/>
      <stop offset=".52" stop-color="#155e75"/>
      <stop offset="1" stop-color="#020617"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="18" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect width="1200" height="900" fill="url(#bg)"/>
  <circle cx="270" cy="230" r="145" fill="#22d3ee" opacity=".34" filter="url(#glow)"/>
  <circle cx="860" cy="590" r="210" fill="#a3e635" opacity=".24" filter="url(#glow)"/>
  <path d="M90 690 C260 520 420 780 610 610 S920 420 1110 560" fill="none" stroke="#f8fafc" stroke-width="18" opacity=".78"/>
  <text x="86" y="140" fill="#ecfeff" font-family="Inter,Arial,sans-serif" font-size="58" font-weight="800">Yahaha Create</text>
  <text x="86" y="784" fill="#ffffff" font-family="Inter,Arial,sans-serif" font-size="76" font-weight="900">{safe_title}</text>
</svg>
"""
    return svg.encode("utf-8")


def _content_type_for_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".json":
        return "application/json"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".wav":
        return "audio/wav"
    return "application/octet-stream"


def _artifact_kind_for_path(path: str) -> str:
    name = PurePosixPath(path).name.lower()
    if name == "index.html":
        return "bundle"
    if name == "source.json":
        return "source"
    if name.startswith("cover.") or name.startswith("thumbnail."):
        return "cover"
    return "generated"


def _safe_artifact_path(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = [part for part in normalized.parts if part not in {"", ".", ".."}]
    safe = "/".join(parts)
    return safe or "asset.bin"


def build_pipeline_from_main_agent_output(
    *,
    prompt: str,
    agent_mode: str,
    game_slug: str,
    game_id: str,
    version_id: str,
    ai_config: dict[str, str],
    parsed_output: dict[str, Any],
    prompt_template: dict | None = None,
    agent_strategy: dict | None = None,
    llm_metrics: dict[str, Any] | None = None,
) -> AgentPipelineResult:
    mode = normalize_agent_mode(agent_mode)
    cover = parsed_output.get("cover") if isinstance(parsed_output.get("cover"), dict) else {}
    title = str(cover.get("title") or title_from_prompt(prompt))[:80]
    description = str(cover.get("description") or prompt)
    files = parsed_output.get("files") if isinstance(parsed_output.get("files"), list) else []
    artifacts: list[AgentArtifact] = []
    source_content: str | None = None
    has_cover = False

    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        path = _safe_artifact_path(str(file_entry.get("path", "")))
        if PurePosixPath(path).name == "manifest.json":
            continue
        content = str(file_entry.get("content", "")).encode("utf-8")
        kind = _artifact_kind_for_path(path)
        if kind == "source":
            source_content = str(file_entry.get("content", ""))
        if kind == "cover":
            has_cover = True
        artifacts.append(
            AgentArtifact(
                filename=path,
                content=content,
                content_type=_content_type_for_path(path),
                kind=kind,
                purpose="final" if kind == "bundle" else "generated",
            )
        )

    if not any(artifact.filename == "index.html" for artifact in artifacts):
        raise ValueError("main agent output must include index.html")

    source_document: dict[str, Any]
    if source_content:
        try:
            loaded_source = json.loads(source_content)
            source_document = loaded_source if isinstance(loaded_source, dict) else {}
        except json.JSONDecodeError:
            source_document = {"rawSource": source_content[:4000]}
    else:
        source_document = {}
    source_document.update(
        {
            "prompt": prompt,
            "agentMode": mode,
            "aiConfig": {
                "baseUrl": ai_config["baseUrl"],
                "model": ai_config["model"],
                "provider": ai_config["provider"],
            },
            "stubbed": False,
            "promptTemplate": prompt_template or {},
            "agentStrategy": agent_strategy or {},
            "llmMetrics": llm_metrics or {},
            "implementationSummary": parsed_output.get("implementationSummary", ""),
            "safetyNotes": parsed_output.get("safetyNotes", []),
            "files": [artifact.filename for artifact in artifacts],
        }
    )
    artifacts = [artifact for artifact in artifacts if artifact.filename != "source.json"]
    artifacts.append(
        AgentArtifact(
            "source.json",
            json.dumps(source_document, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json",
            "source",
            "generated",
        )
    )
    if not has_cover:
        artifacts.append(AgentArtifact("cover.svg", build_cover_svg(title), "image/svg+xml", "cover", "preview"))

    return AgentPipelineResult(
        title=title,
        description=description,
        runtime="iframe-srcdoc",
        entry_file="index.html",
        artifacts=artifacts,
        runs=[
            AgentRunRecord(
                stage="planner",
                status="succeeded",
                input_summary=f"{mode} mode planned the game from the user request.",
                output_summary=str(parsed_output.get("implementationSummary") or "LLM output accepted."),
                log={"stubbed": False, "agentMode": mode, "llmMetrics": llm_metrics or {}},
            ),
            AgentRunRecord(
                stage="game_code",
                status="succeeded",
                input_summary="LLM returned game artifact files.",
                output_summary="index.html/source.json and optional assets are ready for build packaging.",
                log={"stubbed": False, "agentMode": mode, "files": [artifact.filename for artifact in artifacts]},
            ),
            AgentRunRecord(
                stage="build",
                status="succeeded",
                input_summary="Validated required artifact set.",
                output_summary="Backend manifest will be generated from SQL/MinIO metadata.",
                log={"stubbed": False, "agentMode": mode},
            ),
            AgentRunRecord(
                stage="safety",
                status="succeeded",
                input_summary="Accepted LLM safety notes for MVP validation.",
                output_summary="Full static safety scanner is still a follow-up item.",
                log={"stubbed": False, "agentMode": mode, "safetyNotes": parsed_output.get("safetyNotes", [])},
            ),
        ],
        source=source_document,
    )


def mode_run_records(agent_mode: str, html_size: int) -> list[AgentRunRecord]:
    mode_messages = {
        "chat": "Chat mode keeps a direct prompt-to-game flow for fast iteration.",
        "react": "ReAct mode reserves reasoning/action loops for tool-using agents.",
        "plan": "Plan mode reserves a planning pass before code generation.",
        "refine": "Refine mode reserves inspection and targeted improvement passes over an existing game.",
        "centralized": "Centralized mode reserves a main agent that coordinates sub-agent work.",
        "decentralized": "Decentralized mode reserves peer agents that coordinate through shared run state.",
        "init": "Init mode reserves project bootstrap and baseline game scaffolding.",
        "opt": "Opt mode reserves optimization and polish passes over an existing game.",
    }
    return [
        AgentRunRecord(
            stage="planner",
            status="skipped",
            input_summary=f"{agent_mode} mode received the prompt.",
            output_summary=mode_messages[agent_mode],
            log={"stubbed": True, "agentMode": agent_mode},
        ),
        AgentRunRecord(
            stage="game_code",
            status="succeeded",
            input_summary="Generated iframe-safe HTML game document.",
            output_summary="Canvas game includes pointer, keyboard, RAF loop, and postMessage events.",
            log={"stubbed": True, "agentMode": agent_mode, "bytes": html_size},
        ),
        AgentRunRecord(
            stage="build",
            status="succeeded",
            input_summary="Packaged index.html, manifest.json, and source.json.",
            output_summary="Static bundle is ready for MinIO upload.",
            log={"stubbed": True, "agentMode": agent_mode},
        ),
        AgentRunRecord(
            stage="safety",
            status="succeeded",
            input_summary="Checked generated document for iframe runtime constraints.",
            output_summary="No privileged parent access, pointer lock, or secret usage is included.",
            log={"stubbed": True, "agentMode": agent_mode},
        ),
    ]


def run_create_pipeline(
    *,
    prompt: str,
    agent_mode: str,
    game_slug: str,
    game_id: str,
    version_id: str,
    ai_config: dict[str, str],
    prompt_template: dict | None = None,
    agent_strategy: dict | None = None,
) -> AgentPipelineResult:
    mode = normalize_agent_mode(agent_mode)
    title = title_from_prompt(prompt)
    html = build_static_game_html(title, game_slug, game_id, version_id, prompt, mode).encode("utf-8")
    cover = build_cover_svg(title)
    source = {
        "prompt": prompt,
        "agentMode": mode,
        "aiConfig": {
            "baseUrl": ai_config["baseUrl"],
            "model": ai_config["model"],
            "provider": ai_config["provider"],
        },
        "stubbed": True,
        "promptTemplate": prompt_template or {},
        "agentStrategy": agent_strategy or {},
        "files": ["index.html", "manifest.json", "source.json", "cover.svg"],
    }
    return AgentPipelineResult(
        title=title,
        description=prompt,
        runtime="iframe-srcdoc",
        entry_file="index.html",
        artifacts=[
            AgentArtifact("index.html", html, "text/html; charset=utf-8", "bundle", "final"),
            AgentArtifact("source.json", json.dumps(source, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", "source", "generated"),
            AgentArtifact("cover.svg", cover, "image/svg+xml", "cover", "preview"),
        ],
        runs=mode_run_records(mode, len(html)),
        source=source,
    )
