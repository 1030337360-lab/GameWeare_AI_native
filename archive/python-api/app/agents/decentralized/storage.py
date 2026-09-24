from __future__ import annotations

import json
from typing import Any

from app.agents.decentralized.types import DecentralizedCandidate, DecentralizedPreviewState
from app.services.auth_service import redis_client

PREVIEW_KEY_PREFIX = "create:decentralized:preview:"
SELECTION_KEY_PREFIX = "create:decentralized:selection:"
DECENTRALIZED_PREVIEW_TTL_SECONDS = 60 * 60 * 24


def preview_cache_key(run_id: str) -> str:
    return f"{PREVIEW_KEY_PREFIX}{run_id}"


def selection_cache_key(run_id: str) -> str:
    return f"{SELECTION_KEY_PREFIX}{run_id}"


def save_preview_state(state: DecentralizedPreviewState, *, ttl_seconds: int = DECENTRALIZED_PREVIEW_TTL_SECONDS) -> None:
    redis_client().setex(preview_cache_key(state.run_id), ttl_seconds, json.dumps(state.to_public_dict(), ensure_ascii=False, default=str))


def load_preview_state(run_id: str) -> DecentralizedPreviewState | None:
    cached = redis_client().get(preview_cache_key(run_id))
    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        return None
    candidates = []
    for item in payload.get("candidates", []):
        if not isinstance(item, dict):
            continue
        candidates.append(
            DecentralizedCandidate(
                candidate_id=str(item.get("candidateId") or ""),
                title=str(item.get("title") or ""),
                concept_summary=str(item.get("conceptSummary") or ""),
                expert_role=str(item.get("expertRole") or ""),
                expert_domain=str(item.get("expertDomain") or ""),
                expert_intro=str(item.get("expertIntro") or ""),
                style_tags=[str(tag) for tag in item.get("styleTags", []) if isinstance(tag, (str, int))],
                static_html=str(item.get("staticHtml") or ""),
            )
        )
    if not candidates:
        return None
    return DecentralizedPreviewState(
        run_id=run_id,
        job_id=str(payload.get("jobId") or ""),
        selected_candidate_id=payload.get("selectedCandidateId") if isinstance(payload.get("selectedCandidateId"), str) else None,
        phase=str(payload.get("phase") or "preview_ready"),
        candidates=candidates,
    )


def save_selection(run_id: str, candidate_id: str, *, ttl_seconds: int = DECENTRALIZED_PREVIEW_TTL_SECONDS) -> None:
    redis_client().setex(selection_cache_key(run_id), ttl_seconds, json.dumps({"candidateId": candidate_id}, ensure_ascii=False))


def load_selection(run_id: str) -> str | None:
    cached = redis_client().get(selection_cache_key(run_id))
    if not cached:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        return None
    return payload.get("candidateId") if isinstance(payload.get("candidateId"), str) else None


def clear_decentralized_cache(run_id: str) -> None:
    redis_client().delete(preview_cache_key(run_id))
    redis_client().delete(selection_cache_key(run_id))


def selected_candidate(state: DecentralizedPreviewState, candidate_id: str | None) -> dict[str, Any] | None:
    for candidate in state.candidates:
        if candidate.candidate_id == candidate_id:
            return candidate.to_public_dict()
    return None
