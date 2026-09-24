from __future__ import annotations

import base64
import json
import re
from html import escape
from typing import Any
from uuid import uuid4

from app.agents.create import AgentArtifact
from app.agents.create.output_parser import parse_main_agent_json_output
from app.agents.decentralized.types import DecentralizedCandidate


def _json_object(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = value.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM output root must be a JSON object")
    return parsed


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def fallback_experts(user_request: str) -> list[dict[str, Any]]:
    anchors = [
        ("Urban Night Market Curator", "food culture and street installation", ["neon", "dense", "festive"]),
        ("Museum Exhibition Architect", "spatial storytelling", ["gallery", "minimal", "dramatic"]),
        ("Extreme Sports Broadcast Director", "live sports media", ["kinetic", "bold", "spectator"]),
    ]
    return [
        {
            "role": role,
            "domain": domain,
            "selfIntroduction": (
                f"I transform the request into a distinct play mood through {domain}. "
                f"I focus on materials, pacing, audience emotion, and visual rhythm, using {user_request[:80]} as the seed for a surprising game-world direction."
            ),
            "styleTags": tags,
            "creativeAngle": f"Reframe the idea through {domain}.",
        }
        for role, domain, tags in anchors
    ]


def parse_experts(value: str | dict[str, Any], user_request: str) -> list[dict[str, Any]]:
    try:
        payload = _json_object(value)
    except Exception:
        return fallback_experts(user_request)
    experts = _as_list(payload.get("experts"))
    normalized: list[dict[str, Any]] = []
    for item in experts[:3]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        intro = str(item.get("selfIntroduction") or item.get("intro") or "").strip()
        if not role or not intro:
            continue
        tags = [str(tag)[:40] for tag in _as_list(item.get("styleTags")) if isinstance(tag, (str, int))][:6]
        normalized.append(
            {
                "role": role[:120],
                "domain": str(item.get("domain") or "creative practice")[:120],
                "selfIntroduction": intro[:900],
                "styleTags": tags or ["distinctive", "playful", "visual"],
                "creativeAngle": str(item.get("creativeAngle") or "")[:500],
            }
        )
    while len(normalized) < 3:
        normalized.append(fallback_experts(user_request)[len(normalized)])
    return normalized[:3]


def static_preview_fallback(*, user_request: str, expert: dict[str, Any], index: int) -> DecentralizedCandidate:
    title = f"{expert.get('role', 'Creative')} Direction"
    tags = [str(tag) for tag in _as_list(expert.get("styleTags"))][:6] or ["arcade", "concept"]
    tag_markup = "".join(f"<span>{escape(tag)}</span>" for tag in tags)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#10131b;color:#f8fbff;font-family:Inter,Arial,sans-serif}}
.scene{{min-height:100vh;display:grid;place-items:center;background:radial-gradient(circle at 25% 25%,#34d39955,transparent 28%),linear-gradient(135deg,#10131b,#2d1b69)}}
.board{{width:min(86vw,860px);aspect-ratio:16/10;border:1px solid #ffffff24;border-radius:8px;background:#05070dcc;position:relative;overflow:hidden;box-shadow:0 24px 80px #0009}}
.lane{{position:absolute;inset:12%;border:2px solid #ffffff30;transform:skew(-8deg);background:linear-gradient(90deg,#ffffff08,#ffffff18)}}
.hero{{position:absolute;left:9%;top:12%;max-width:48%;display:grid;gap:10px}}
h1{{font-size:clamp(24px,5vw,58px);margin:0;line-height:.95}}p{{color:#cbd5e1;margin:0}}.tags{{display:flex;gap:6px;flex-wrap:wrap}}span{{font-size:12px;background:#ffffff18;border:1px solid #ffffff28;border-radius:999px;padding:5px 8px}}
.piece{{position:absolute;right:16%;bottom:18%;width:24%;aspect-ratio:1;border-radius:22%;background:linear-gradient(135deg,#facc15,#fb7185);box-shadow:0 0 50px #fb718588}}
</style></head><body><main class="scene"><section class="board"><div class="lane"></div><div class="hero"><h1>{escape(title)}</h1><p>{escape(user_request[:220])}</p><div class="tags">{tag_markup}</div></div><div class="piece"></div></section></main></body></html>"""
    return DecentralizedCandidate(
        candidate_id=f"candidate-{index}",
        title=title[:120],
        concept_summary=f"A static visual direction shaped by {expert.get('role', 'a creative expert')}.",
        expert_role=str(expert.get("role") or "Creative Expert"),
        expert_domain=str(expert.get("domain") or "creative practice"),
        expert_intro=str(expert.get("selfIntroduction") or "")[:900],
        style_tags=tags,
        static_html=html,
    )


def parse_preview(value: str | dict[str, Any], *, user_request: str, expert: dict[str, Any], index: int) -> DecentralizedCandidate:
    try:
        payload = _json_object(value)
    except Exception:
        return static_preview_fallback(user_request=user_request, expert=expert, index=index)
    static_html = str(payload.get("staticHtml") or payload.get("html") or "").strip()
    if "<html" not in static_html.lower() or len(static_html) < 120:
        return static_preview_fallback(user_request=user_request, expert=expert, index=index)
    tags = [str(tag)[:40] for tag in _as_list(payload.get("styleTags")) if isinstance(tag, (str, int))][:6]
    if not tags:
        tags = [str(tag) for tag in _as_list(expert.get("styleTags"))][:6] or ["preview"]
    return DecentralizedCandidate(
        candidate_id=f"candidate-{index}",
        title=str(payload.get("title") or expert.get("role") or f"Candidate {index}")[:120],
        concept_summary=str(payload.get("conceptSummary") or payload.get("summary") or "")[:600],
        expert_role=str(expert.get("role") or "Creative Expert")[:120],
        expert_domain=str(expert.get("domain") or "creative practice")[:120],
        expert_intro=str(expert.get("selfIntroduction") or "")[:900],
        style_tags=tags,
        static_html=static_html[:120000],
    )


def parse_final_game(value: str | dict[str, Any]) -> dict[str, Any]:
    parsed = parse_main_agent_json_output(value)
    if parsed.get("fallback"):
        raise ValueError(str(parsed.get("fallbackReason") or "invalid_final_game_output"))
    return parsed


def parse_cover_artifact(value: str | dict[str, Any]) -> AgentArtifact:
    payload = _json_object(value)
    mime_type = str(payload.get("mimeType") or payload.get("contentType") or "image/png").split(";", 1)[0]
    if isinstance(payload.get("imageBase64"), str):
        content = base64.b64decode(payload["imageBase64"], validate=True)
        if not content:
            raise ValueError("cover image is empty")
        extension = {"image/png": "png", "image/webp": "webp", "image/jpeg": "jpg"}.get(mime_type, "png")
        return AgentArtifact(f"cover.{extension}", content, mime_type, "cover", "preview")
    svg = str(payload.get("svg") or "").strip()
    if svg:
        if "<svg" not in svg.lower() or "</svg>" not in svg.lower():
            raise ValueError("cover svg fallback must contain a complete svg document")
        return AgentArtifact("cover.svg", svg.encode("utf-8"), "image/svg+xml", "cover", "preview")
    raise ValueError("cover output must include imageBase64 or svg")


def source_metadata_file(*, selected_candidate: dict[str, Any], template_metadata: dict[str, Any], warnings: list[str] | None = None) -> dict[str, str]:
    return {
        "path": "source.json",
        "content": json.dumps(
            {
                "generator": "decentralized-two-phase",
                "selectedCandidate": {
                    "candidateId": selected_candidate.get("candidateId"),
                    "title": selected_candidate.get("title"),
                    "expertRole": selected_candidate.get("expertRole"),
                    "styleTags": selected_candidate.get("styleTags"),
                },
                "promptTemplates": template_metadata,
                "normalizationWarnings": warnings or [],
                "traceId": str(uuid4()),
            },
            ensure_ascii=False,
            indent=2,
        ),
    }
