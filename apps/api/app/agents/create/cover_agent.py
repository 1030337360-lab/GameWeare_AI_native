from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.create.pipeline import AgentArtifact
from app.agents.graphs.llm_adapter import LLMGraphAdapter, LLMGraphResult, build_llm_call_metrics

COVER_AGENT_NAME = "cover-agent"
COVER_AGENT_VERSION = "2026-06-19"
COVER_WIDTH = 1200
COVER_HEIGHT = 900
SUPPORTED_IMAGE_TYPES = {
    "image/png": "cover.png",
    "image/webp": "cover.webp",
    "image/jpeg": "cover.jpg",
    "image/svg+xml": "cover.svg",
}


@dataclass(frozen=True)
class CoverAgentArtifact:
    artifact: AgentArtifact
    width: int = COVER_WIDTH
    height: int = COVER_HEIGHT
    summary: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    raw_kind: str = "unknown"

    @property
    def content_type(self) -> str:
        return self.artifact.content_type

    @property
    def size_bytes(self) -> int:
        return len(self.artifact.content)


def build_cover_responses_payload(
    *,
    model: str,
    user_request: str,
    game_title: str,
    game_description: str,
    implementation_summary: str = "",
    style_tags: list[str] | None = None,
    max_output_tokens: int = 4000,
) -> dict[str, Any]:
    tags = [tag for tag in (style_tags or []) if isinstance(tag, str) and tag.strip()]
    system_prompt = f"""You are the Yahaha Cover Agent.

Create one cover image for an iframe HTML5 game. The cover must be a durable game catalog asset, not placeholder art.

Hard requirements:
- Target size: {COVER_WIDTH}x{COVER_HEIGHT}, 4:3.
- Use the user's request, game title, gameplay summary, and style tags.
- Return exactly one JSON object and no markdown fences.
- Preferred output: {{"imageBase64":"...","mimeType":"image/png","summary":"..."}} or image/webp.
- If the provider cannot return raster image data, return {{"svg":"<svg ...>...</svg>","mimeType":"image/svg+xml","summary":"..."}}.
- Do not return external image URLs.
- Do not include secrets, API keys, or backend-only identifiers.
- Do not return a generic template cover.
"""
    user_prompt = json.dumps(
        {
            "createRequest": user_request,
            "gameTitle": game_title,
            "gameDescription": game_description,
            "implementationSummary": implementation_summary,
            "styleTags": tags,
            "coverSpec": {
                "width": COVER_WIDTH,
                "height": COVER_HEIGHT,
                "aspectRatio": "4:3",
                "usage": "home grid card, game detail hero, play manifest asset",
            },
            "outputContract": {
                "imageBase64": "base64 encoded PNG/WebP/JPEG image bytes, preferred",
                "mimeType": "image/png | image/webp | image/jpeg | image/svg+xml",
                "svg": "SVG string fallback only when raster image is not available",
                "summary": "short non-secret generation summary",
            },
        },
        ensure_ascii=False,
    )
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        "reasoning": {"effort": "medium"},
        "max_output_tokens": max_output_tokens,
    }


def _json_from_text(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _decode_base64_image(value: str) -> tuple[bytes, str | None]:
    cleaned = value.strip()
    mime_type: str | None = None
    if cleaned.startswith("data:"):
        header, _, body = cleaned.partition(",")
        cleaned = body
        header_match = re.match(r"data:([^;]+);base64", header)
        if header_match:
            mime_type = header_match.group(1)
    try:
        return base64.b64decode(cleaned, validate=True), mime_type
    except (binascii.Error, ValueError) as exc:
        raise ValueError("cover imageBase64 is not valid base64") from exc


def _svg_bytes(svg: str) -> bytes:
    content = svg.strip()
    if not content.startswith("<svg") or "</svg>" not in content:
        raise ValueError("cover svg fallback must contain one complete <svg> document")
    return content.encode("utf-8")


def _filename_for_type(mime_type: str) -> str:
    return SUPPORTED_IMAGE_TYPES.get(mime_type, "cover.png")


def _extract_response_image(raw: dict[str, Any]) -> tuple[str, str] | None:
    """Best-effort support for Responses providers that return image chunks outside text."""
    output = raw.get("output")
    if not isinstance(output, list):
        return None
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            mime_type = str(content_item.get("mime_type") or content_item.get("mimeType") or "image/png")
            for key in ("image_base64", "imageBase64", "b64_json", "data"):
                value = content_item.get(key)
                if isinstance(value, str) and value.strip():
                    return value, mime_type
    return None


def parse_cover_agent_output(result: LLMGraphResult) -> CoverAgentArtifact:
    parsed = _json_from_text(result.text)
    payload = parsed or {}
    summary = str(payload.get("summary") or "Cover image generated by cover agent.")[:500]

    image_value = payload.get("imageBase64") or payload.get("image_base64") or payload.get("b64_json")
    mime_type = str(payload.get("mimeType") or payload.get("mime_type") or "image/png")
    raw_kind = "base64"
    if not isinstance(image_value, str) or not image_value.strip():
        extracted = _extract_response_image(result.raw)
        if extracted:
            image_value, extracted_mime = extracted
            mime_type = str(payload.get("mimeType") or payload.get("mime_type") or extracted_mime or "image/png")

    if isinstance(image_value, str) and image_value.strip():
        content, detected_mime = _decode_base64_image(image_value)
        mime_type = detected_mime or mime_type
        if mime_type not in SUPPORTED_IMAGE_TYPES or mime_type == "image/svg+xml":
            mime_type = "image/png"
        if not content:
            raise ValueError("cover image is empty")
        return CoverAgentArtifact(
            artifact=AgentArtifact(_filename_for_type(mime_type), content, mime_type, "cover", "preview"),
            summary=summary,
            metrics=_cover_metrics(result),
            raw_kind=raw_kind,
        )

    svg = payload.get("svg") if isinstance(payload.get("svg"), str) else result.text.strip()
    if isinstance(svg, str) and svg.strip().startswith("<svg"):
        content = _svg_bytes(svg)
        return CoverAgentArtifact(
            artifact=AgentArtifact("cover.svg", content, "image/svg+xml", "cover", "preview"),
            summary=summary if parsed else "Cover SVG generated by cover agent.",
            metrics=_cover_metrics(result),
            raw_kind="svg",
        )

    raise ValueError("cover agent output must include imageBase64 or svg")


def _cover_metrics(result: LLMGraphResult) -> dict[str, Any]:
    metrics = dict(result.metrics or {})
    if "promptPrefix" in metrics:
        metrics["promptPrefix"] = str(metrics["promptPrefix"])[:600]
    metrics["rawKind"] = "cover_generation"
    return metrics


def generate_cover_artifact(
    *,
    adapter: LLMGraphAdapter,
    model: str,
    user_request: str,
    game_title: str,
    game_description: str,
    implementation_summary: str = "",
    style_tags: list[str] | None = None,
) -> tuple[CoverAgentArtifact, dict[str, Any], LLMGraphResult]:
    payload = build_cover_responses_payload(
        model=model,
        user_request=user_request,
        game_title=game_title,
        game_description=game_description,
        implementation_summary=implementation_summary,
        style_tags=style_tags,
    )
    result = adapter.invoke(payload)
    if isinstance(result.raw, dict) and result.raw.get("ok") is False:
        raise RuntimeError("Cover Agent provider call failed.")
    if not result.text and not _extract_response_image(result.raw):
        result = LLMGraphResult(
            text=result.text,
            raw=result.raw,
            metrics=build_llm_call_metrics(payload, response_text=result.text, response_raw=result.raw),
        )
    return parse_cover_agent_output(result), payload, result
