from __future__ import annotations

import json
from typing import Any


EXPERT_TEMPLATE_NAME = "yahaha-decentralized-expert-factory"
EXPERT_TEMPLATE_VERSION = "2026-06-20.1"
PREVIEW_TEMPLATE_NAME = "yahaha-decentralized-static-preview"
PREVIEW_TEMPLATE_VERSION = "2026-06-20.1"
FINAL_TEMPLATE_NAME = "yahaha-decentralized-final-game"
FINAL_TEMPLATE_VERSION = "2026-06-20.1"
COVER_TEMPLATE_NAME = "yahaha-decentralized-cover"
COVER_TEMPLATE_VERSION = "2026-06-20.1"


def _responses_payload(*, model: str, system: str, user: str, max_output_tokens: int = 25000) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "reasoning": {"effort": "medium"},
        "max_output_tokens": max_output_tokens,
    }


def multimodal_summary(input_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "assetId": asset.get("assetId"),
            "filename": asset.get("filename"),
            "contentType": asset.get("contentType"),
            "size": asset.get("size"),
            "publicUrl": asset.get("publicUrl"),
        }
        for asset in input_assets
    ]


def _previous_project_context(previous_project_context: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return previous_project_context or []


def _intent_label(previous_project_context: list[dict[str, Any]] | None) -> str:
    return "continue" if previous_project_context else "init"


def _intent_rules(previous_project_context: list[dict[str, Any]] | None) -> list[str]:
    if previous_project_context:
        return [
            "This is a continuation of an existing creator project.",
            "Use previousProjectContext as the prior playable version baseline.",
            "Generate directions that optimize or evolve the existing game instead of ignoring it.",
            "Preserve working behavior unless the creator request asks for a change.",
            "The final output contract remains identical to initial creation.",
        ]
    return [
        "This is an initial creation for a new creator project.",
        "Generate directions from the creator request and multimodal inputs.",
        "The final output contract is the standard Yahaha playable game package.",
    ]


def build_expert_payload(
    *,
    model: str,
    user_request: str,
    input_assets: list[dict[str, Any]],
    previous_project_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system = """You are the Yahaha Decentralized Expert Factory.
Return exactly one JSON object and no markdown.
Generate three highly different creative professional experts related to the creator request and multimodal inputs.
Each expert must be a real-world creative or professional role, not a generic game designer.
Each expert must include a roughly 50-word first-person selfIntroduction that can be injected into a later system prompt.
Do not include backend IDs, tokens, secrets, api keys, or implementation metadata."""
    user = json.dumps(
        {
            "createRequest": user_request,
            "creationIntent": _intent_label(previous_project_context),
            "intentRules": _intent_rules(previous_project_context),
            "multimodalInputs": multimodal_summary(input_assets),
            "previousProjectContext": _previous_project_context(previous_project_context),
            "requiredOutput": {
                "experts": [
                    {
                        "role": "profession title",
                        "domain": "industry/domain",
                        "selfIntroduction": "around 50 words",
                        "styleTags": ["3-6 style tags"],
                        "creativeAngle": "how this expert changes the game direction",
                    }
                ]
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    return _responses_payload(model=model, system=system, user=user, max_output_tokens=4000)


def build_preview_payload(
    *,
    model: str,
    user_request: str,
    input_assets: list[dict[str, Any]],
    expert: dict[str, Any],
    candidate_index: int,
    previous_project_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system = f"""You are two cooperating agents inside Yahaha Create.

Creative expert system injection:
Role: {expert.get("role", "Creative Expert")}
Domain: {expert.get("domain", "creative practice")}
Self introduction: {expert.get("selfIntroduction", "")}

Fixed Game Preview Expert rules:
- Generate one static, non-playable HTML game interface preview.
- The preview should inspire the creator with a distinct game style, camera, composition, color system, and visible UI/game-state hints.
- Do not implement playable controls, scoring logic, win/lose loop, postMessage game_start, database fields, manifest, or source metadata.
- The HTML must be self-contained and safe for iframe srcdoc.
- Return exactly one JSON object and no markdown."""
    user = json.dumps(
        {
            "candidateIndex": candidate_index,
            "createRequest": user_request,
            "creationIntent": _intent_label(previous_project_context),
            "intentRules": _intent_rules(previous_project_context),
            "multimodalInputs": multimodal_summary(input_assets),
            "previousProjectContext": _previous_project_context(previous_project_context),
            "expert": expert,
            "requiredOutput": {
                "title": "candidate title",
                "conceptSummary": "short summary",
                "styleTags": ["style tags"],
                "staticHtml": "<!doctype html>...",
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    return _responses_payload(model=model, system=system, user=user, max_output_tokens=10000)


def build_final_game_payload(
    *,
    model: str,
    user_request: str,
    input_assets: list[dict[str, Any]],
    candidate: dict[str, Any],
    workspace_boundary: str,
    previous_project_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    system = """You are the Yahaha Decentralized Final Game Agent.
Return exactly one JSON object and no markdown.
Use the selected static preview as creative direction, but now produce a fully playable iframe HTML5 game.
The final output must be:
{"type":"final","output":{"Finished":true,"files":[{"path":"index.html","content":"..."}],"cover":{"title":"...","description":"...","tags":["..."]},"implementationSummary":"...","safetyNotes":["..."]}}
The game must be self-contained in index.html, use Canvas or DOM safely, run continuously with requestAnimationFrame when appropriate, prevent keyboard scrolling, keep cursor visible, and post Yahaha lifecycle messages game_ready and game_start.
Do not include api keys, tokens, backend IDs, remote scripts, eval, local file APIs, pointer lock, or allow-same-origin assumptions."""
    user = json.dumps(
        {
            "createRequest": user_request,
            "creationIntent": _intent_label(previous_project_context),
            "intentRules": _intent_rules(previous_project_context),
            "multimodalInputs": multimodal_summary(input_assets),
            "previousProjectContext": _previous_project_context(previous_project_context),
            "selectedDirection": {
                "candidateId": candidate.get("candidateId"),
                "title": candidate.get("title"),
                "conceptSummary": candidate.get("conceptSummary"),
                "expertRole": candidate.get("expertRole"),
                "expertDomain": candidate.get("expertDomain"),
                "expertIntro": candidate.get("expertIntro"),
                "styleTags": candidate.get("styleTags"),
                "staticHtmlPreview": str(candidate.get("staticHtml", ""))[:50000],
            },
            "workspaceBoundary": workspace_boundary,
        },
        ensure_ascii=False,
        indent=2,
    )
    return _responses_payload(model=model, system=system, user=user)


def build_cover_payload(*, model: str, user_request: str, candidate: dict[str, Any], game_output: dict[str, Any]) -> dict[str, Any]:
    system = """You are the Yahaha Decentralized Cover Agent.
Create one durable 1200x900 game catalog cover for the selected direction and final game.
Return exactly one JSON object and no markdown.
Preferred output is {"imageBase64":"...","mimeType":"image/png","summary":"...","width":1200,"height":900}.
If image generation is unavailable, return {"svg":"<svg ...>...</svg>","mimeType":"image/svg+xml","summary":"...","width":1200,"height":900}.
Do not return placeholders, remote URLs, api keys, tokens, or base64 in explanations."""
    user = json.dumps(
        {
            "createRequest": user_request,
            "selectedDirection": {
                "title": candidate.get("title"),
                "conceptSummary": candidate.get("conceptSummary"),
                "expertRole": candidate.get("expertRole"),
                "styleTags": candidate.get("styleTags"),
            },
            "finalGame": {
                "cover": game_output.get("cover"),
                "implementationSummary": game_output.get("implementationSummary"),
                "safetyNotes": game_output.get("safetyNotes"),
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    return _responses_payload(model=model, system=system, user=user, max_output_tokens=10000)


def template_metadata(name: str, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateName": name,
        "templateVersion": version,
        "renderedCharacters": len(json.dumps(payload, ensure_ascii=False, default=str)),
    }
