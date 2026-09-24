from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from app.agents.create import AgentArtifact, AgentPipelineResult, AgentRunRecord
from app.agents.decentralized.parsers import (
    parse_cover_artifact,
    parse_experts,
    parse_final_game,
    parse_preview,
    source_metadata_file,
)
from app.agents.decentralized.prompts import (
    COVER_TEMPLATE_NAME,
    COVER_TEMPLATE_VERSION,
    EXPERT_TEMPLATE_NAME,
    EXPERT_TEMPLATE_VERSION,
    FINAL_TEMPLATE_NAME,
    FINAL_TEMPLATE_VERSION,
    PREVIEW_TEMPLATE_NAME,
    PREVIEW_TEMPLATE_VERSION,
    build_cover_payload,
    build_expert_payload,
    build_final_game_payload,
    build_preview_payload,
    template_metadata,
)
from app.agents.decentralized.storage import (
    DECENTRALIZED_PREVIEW_TTL_SECONDS,
    clear_decentralized_cache,
    load_preview_state,
    load_selection,
    save_preview_state,
    save_selection,
    selected_candidate,
)
from app.agents.decentralized.types import DecentralizedPreviewState
from app.agents.graphs.errors import LLMProviderCallError, provider_error_diagnostics
from app.agents.graphs.llm_adapter import LLMGraphAdapter, LLMGraphResult
from app.database import db_connection

COVER_WIDTH = 1200
COVER_HEIGHT = 900


@dataclass(frozen=True)
class DecentralizedFinalResult:
    pipeline: AgentPipelineResult
    cover_artifact: Any
    prompt_template: dict[str, Any]
    strategy_metadata: dict[str, Any]
    llm_metrics: dict[str, Any]


def _invoke_llm(adapter: LLMGraphAdapter, payload: dict[str, Any], *, context: Any, stage: str, summary: str) -> LLMGraphResult:
    result = adapter.invoke(payload)
    metrics = result.metrics if isinstance(result.metrics, dict) else {}
    provider_error = provider_error_diagnostics(result.raw if isinstance(result.raw, dict) else None)
    context.run_log.append(
        stage=stage,
        status="failed" if provider_error else "succeeded",
        input_summary=str(metrics.get("promptPrefix") or "")[:500],
        output_summary=(
            str(provider_error.get("message") or provider_error.get("code"))[:500]
            if provider_error
            else (summary if result.text or result.raw else "LLM returned an empty response.")
        ),
        metrics={
            "promptEnglishWords": metrics.get("promptEnglishWords"),
            "promptChineseChars": metrics.get("promptChineseChars"),
            "prefixEnglishWords": metrics.get("prefixEnglishWords"),
            "prefixChineseChars": metrics.get("prefixChineseChars"),
            "outputEnglishWords": metrics.get("outputEnglishWords"),
            "outputChineseChars": metrics.get("outputChineseChars"),
            "outputTokens": (metrics.get("tokenUsage") or {}).get("outputTokens"),
            "tokenUsage": metrics.get("tokenUsage"),
            "rawKind": stage,
            "providerError": provider_error,
        },
    )
    context.short_term_memory.record_llm_call({"kind": stage, "metrics": metrics, "outputPreview": result.text[:600]})
    context.long_term_memory.append_history("llm", result.text[:1200], metadata={"kind": stage, "metrics": metrics})
    if provider_error:
        raise LLMProviderCallError({**provider_error, "stage": stage})
    return result


def _safe_candidate_metrics(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": candidate.get("candidateId"),
        "title": candidate.get("title"),
        "conceptSummary": str(candidate.get("conceptSummary") or "")[:500],
        "expertRole": candidate.get("expertRole"),
        "expertDomain": candidate.get("expertDomain"),
        "expertIntro": str(candidate.get("expertIntro") or "")[:900],
        "styleTags": candidate.get("styleTags") if isinstance(candidate.get("styleTags"), list) else [],
        "staticHtmlChars": len(str(candidate.get("staticHtml") or "")),
    }


def _safe_svg_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").strip()[:limit]
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _decentralized_fallback_cover(*, selected: dict[str, Any], reason: str) -> AgentArtifact:
    title = _safe_svg_text(selected.get("title") or "Decentralized Game", 90)
    expert = _safe_svg_text(selected.get("expertRole") or "Creative direction", 120)
    summary = _safe_svg_text(selected.get("conceptSummary") or reason, 150)
    safe_reason = _safe_svg_text(reason, 120)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{COVER_WIDTH}" height="{COVER_HEIGHT}" viewBox="0 0 {COVER_WIDTH} {COVER_HEIGHT}" role="img" aria-label="{title}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0f172a"/>
      <stop offset="0.55" stop-color="#155e75"/>
      <stop offset="1" stop-color="#854d0e"/>
    </linearGradient>
    <pattern id="dots" width="48" height="48" patternUnits="userSpaceOnUse">
      <circle cx="8" cy="8" r="3" fill="#ffffff" opacity="0.16"/>
    </pattern>
  </defs>
  <rect width="1200" height="900" fill="url(#bg)"/>
  <rect width="1200" height="900" fill="url(#dots)"/>
  <rect x="76" y="92" width="1048" height="716" rx="34" fill="#020617" fill-opacity="0.56" stroke="#e2e8f0" stroke-opacity="0.22" stroke-width="3"/>
  <path d="M178 624 C330 450 482 712 636 500 C760 328 902 330 1048 188" fill="none" stroke="#22d3ee" stroke-width="18" stroke-linecap="round"/>
  <circle cx="902" cy="294" r="112" fill="#f59e0b" fill-opacity="0.88"/>
  <circle cx="986" cy="360" r="70" fill="#e879f9" fill-opacity="0.74"/>
  <text x="124" y="248" fill="#f8fafc" font-family="Arial, Helvetica, sans-serif" font-size="72" font-weight="800">{title}</text>
  <text x="128" y="322" fill="#bae6fd" font-family="Arial, Helvetica, sans-serif" font-size="30">{expert}</text>
  <text x="128" y="394" fill="#cbd5e1" font-family="Arial, Helvetica, sans-serif" font-size="26">{summary}</text>
  <text x="128" y="736" fill="#fed7aa" font-family="Arial, Helvetica, sans-serif" font-size="24">Fallback decentralized cover: {safe_reason}</text>
</svg>"""
    return AgentArtifact("cover.svg", svg.encode("utf-8"), "image/svg+xml", "cover", "fallback")


def _cover_wrapper(artifact: AgentArtifact, *, raw_kind: str, summary: str) -> Any:
    return type(
        "DecentralizedCoverArtifact",
        (),
        {
            "artifact": artifact,
            "content_type": artifact.content_type,
            "width": COVER_WIDTH,
            "height": COVER_HEIGHT,
            "size_bytes": len(artifact.content),
            "raw_kind": raw_kind,
            "summary": summary,
        },
    )()


def _pipeline_from_final_output(
    *,
    prompt: str,
    agent_mode: str,
    game_slug: str,
    game_id: str,
    version_id: str,
    ai_config: dict[str, str],
    parsed_output: dict[str, Any],
    selected: dict[str, Any],
    prompt_template: dict[str, Any],
    strategy_metadata: dict[str, Any],
    llm_metrics: dict[str, Any],
) -> AgentPipelineResult:
    artifacts: list[AgentArtifact] = []
    source_added = False
    for entry in parsed_output.get("files", []):
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "asset.txt").replace("\\", "/").split("/")[-1] or "asset.txt"
        if path == "manifest.json":
            continue
        content = str(entry.get("content") or "").encode("utf-8")
        content_type = "text/html; charset=utf-8" if path.endswith(".html") else "application/json" if path.endswith(".json") else "text/plain"
        kind = "bundle" if path == "index.html" else "source" if path == "source.json" else "manifest" if path == "manifest.json" else "asset"
        if path == "source.json":
            source_added = True
        artifacts.append(AgentArtifact(path, content, content_type, kind, "final"))
    if not source_added:
        source = source_metadata_file(
            selected_candidate=selected,
            template_metadata=prompt_template,
            warnings=parsed_output.get("normalizationWarnings") if isinstance(parsed_output.get("normalizationWarnings"), list) else [],
        )
        artifacts.append(AgentArtifact("source.json", source["content"].encode("utf-8"), "application/json", "source", "source"))
    cover = parsed_output.get("cover") if isinstance(parsed_output.get("cover"), dict) else {}
    title = str(cover.get("title") or selected.get("title") or "Decentralized Game")[:120]
    description = str(cover.get("description") or parsed_output.get("implementationSummary") or prompt)[:1000]
    return AgentPipelineResult(
        title=title,
        description=description,
        runtime="iframe-srcdoc",
        entry_file="index.html",
        artifacts=artifacts,
        runs=[
            AgentRunRecord(
                "game_code",
                "succeeded",
                "Selected preview direction converted into a playable game package.",
                "Final game package accepted by decentralized parser.",
                {
                    "agentMode": agent_mode,
                    "selectedCandidateId": selected.get("candidateId"),
                    "llmMetrics": llm_metrics,
                    "model": ai_config.get("model"),
                },
            )
        ],
        source={
            "agentMode": agent_mode,
            "gameId": game_id,
            "versionId": version_id,
            "gameSlug": game_slug,
            "promptTemplate": prompt_template,
            "agentStrategy": strategy_metadata,
            "selectedCandidate": _safe_candidate_metrics(selected),
        },
    )


def generate_decentralized_previews(
    *,
    job_id: str,
    context: Any,
    user_request: str,
    input_assets: list[dict[str, Any]],
    ai_config: dict[str, str],
    adapter_factory: Callable[[dict[str, str]], LLMGraphAdapter],
    previous_project_context: list[dict[str, Any]] | None = None,
) -> None:
    adapter = adapter_factory(ai_config)
    context.run_log.append(
        stage="decentralized_preview_generation_started",
        status="running",
        input_summary="Decentralized creative preview generation started.",
        output_summary="Three static directions will be generated before any game is published.",
        metrics={"jobId": job_id, "candidateCount": 3, "ttlSeconds": DECENTRALIZED_PREVIEW_TTL_SECONDS},
    )
    expert_payload = build_expert_payload(
        model=ai_config["model"],
        user_request=user_request,
        input_assets=input_assets,
        previous_project_context=previous_project_context,
    )
    context.run_log.append(
        stage="decentralized_expert_prompt_rendered",
        status="succeeded",
        input_summary="Expert factory prompt rendered.",
        output_summary=f"{EXPERT_TEMPLATE_NAME}@{EXPERT_TEMPLATE_VERSION} is ready.",
        metrics=template_metadata(EXPERT_TEMPLATE_NAME, EXPERT_TEMPLATE_VERSION, expert_payload),
    )
    expert_result = _invoke_llm(adapter, expert_payload, context=context, stage="decentralized_expert_llm_call", summary="Expert factory returned candidate expert roles.")
    experts = parse_experts(expert_result.text, user_request)
    context.run_log.append(
        stage="decentralized_experts_generated",
        status="succeeded",
        input_summary="Creative expert roles parsed.",
        output_summary=f"{len(experts)} expert role(s) are ready for static preview generation.",
        metrics={"experts": [{k: v for k, v in expert.items() if k != "selfIntroduction"} for expert in experts]},
    )

    candidates = []
    for index, expert in enumerate(experts, start=1):
        preview_payload = build_preview_payload(
            model=ai_config["model"],
            user_request=user_request,
            input_assets=input_assets,
            expert=expert,
            candidate_index=index,
            previous_project_context=previous_project_context,
        )
        context.run_log.append(
            stage="decentralized_preview_prompt_rendered",
            status="succeeded",
            input_summary=f"Static preview prompt rendered for candidate {index}.",
            output_summary=f"{PREVIEW_TEMPLATE_NAME}@{PREVIEW_TEMPLATE_VERSION} is ready.",
            metrics={
                **template_metadata(PREVIEW_TEMPLATE_NAME, PREVIEW_TEMPLATE_VERSION, preview_payload),
                "candidateIndex": index,
                "expertRole": expert.get("role"),
            },
        )
        preview_result = _invoke_llm(
            adapter,
            preview_payload,
            context=context,
            stage="decentralized_preview_llm_call",
            summary=f"Static preview candidate {index} returned.",
        )
        candidate = parse_preview(preview_result.text, user_request=user_request, expert=expert, index=index)
        candidates.append(candidate)
        context.run_log.append(
            stage="decentralized_preview_candidate",
            status="succeeded",
            input_summary=f"Candidate {candidate.candidate_id} static preview parsed.",
            output_summary=candidate.concept_summary,
            metrics=_safe_candidate_metrics(candidate.to_public_dict()),
        )

    state = DecentralizedPreviewState(
        run_id=context.run_id,
        job_id=job_id,
        selected_candidate_id=None,
        phase="preview_ready",
        candidates=candidates,
    )
    save_preview_state(state)
    public_state = state.to_public_dict()
    context.run_log.append(
        stage="decentralized_preview_ready",
        status="succeeded",
        input_summary="Three static preview candidates are ready for user selection.",
        output_summary="Waiting for the user to choose a direction and confirm.",
        metrics={"previewState": public_state, "candidateCount": len(candidates)},
    )
    context.run_log.append(
        stage="decentralized_waiting_selection",
        status="running",
        input_summary="Decentralized run is waiting for candidate selection.",
        output_summary="No game artifacts have been published.",
        metrics={"candidateIds": [candidate.candidate_id for candidate in candidates]},
    )
    context.task_store.checkpoint(context.task_state, "decentralized_preview_ready", public_state, context.run_log.object_key)
    with db_connection() as connection:
        connection.execute(
            """
UPDATE create_runs
SET summary = %s
WHERE id = %s
""",
            (Jsonb({"phase": "decentralized_preview_ready", "decentralizedPreview": public_state}), context.run_id),
        )
        connection.execute(
            """
UPDATE generation_jobs
SET status = 'planning', current_stage = 'decentralized_preview_ready'
WHERE id = %s
""",
            (job_id,),
        )


def get_decentralized_previews(*, user_id: str, run_id: str) -> dict[str, Any]:
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, agent_mode, summary, job_id
FROM create_runs
WHERE id = %s AND user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["agent_mode"] != "decentralized":
        raise HTTPException(status_code=409, detail={"code": "NOT_DECENTRALIZED_RUN", "message": "Run is not a decentralized run."})
    state = load_preview_state(run_id)
    if state:
        return state.to_public_dict()
    summary = row["summary"] if isinstance(row["summary"], dict) else {}
    preview = summary.get("decentralizedPreview") if isinstance(summary.get("decentralizedPreview"), dict) else None
    if not preview:
        raise HTTPException(status_code=404, detail="Decentralized previews not found")
    return preview


def select_decentralized_candidate(*, user_id: str, run_id: str, candidate_id: str) -> dict[str, Any]:
    state = load_preview_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Decentralized previews not found")
    preview = get_decentralized_previews(user_id=user_id, run_id=run_id)
    if not any(candidate.get("candidateId") == candidate_id for candidate in preview.get("candidates", [])):
        raise HTTPException(status_code=404, detail="Candidate not found")
    save_selection(run_id, candidate_id)
    updated = DecentralizedPreviewState(
        run_id=state.run_id,
        job_id=state.job_id,
        selected_candidate_id=candidate_id,
        phase="candidate_selected",
        candidates=state.candidates,
    )
    save_preview_state(updated)
    with db_connection() as connection:
        connection.execute(
            """
UPDATE create_runs
SET summary = summary || %s
WHERE id = %s AND user_id = %s
""",
            (Jsonb({"phase": "decentralized_candidate_selected", "selectedCandidateId": candidate_id}), run_id, user_id),
        )
    return updated.to_public_dict()


def build_decentralized_final_result(
    *,
    job_id: str,
    context: Any,
    user_request: str,
    input_assets: list[dict[str, Any]],
    ai_config: dict[str, str],
    adapter_factory: Callable[[dict[str, str]], LLMGraphAdapter],
    game_id: str,
    version_id: str,
    game_slug: str,
    previous_project_context: list[dict[str, Any]] | None = None,
) -> DecentralizedFinalResult:
    state = load_preview_state(context.run_id)
    if not state:
        raise RuntimeError("Decentralized previews are no longer available. Please start a new run.")
    candidate_id = load_selection(context.run_id) or state.selected_candidate_id
    selected = selected_candidate(state, candidate_id)
    if not selected:
        raise HTTPException(status_code=409, detail={"code": "DECENTRALIZED_CANDIDATE_REQUIRED", "message": "Select a preview candidate before confirming."})

    adapter = adapter_factory(ai_config)
    strategy_metadata = {
        "strategy": "decentralized",
        "topology": "two-phase-peer-preview",
        "phase": "final_generation",
        "selectedCandidate": _safe_candidate_metrics(selected),
    }
    final_payload = build_final_game_payload(
        model=ai_config["model"],
        user_request=user_request,
        input_assets=input_assets,
        candidate=selected,
        workspace_boundary=context.workspace.worktree_stub_path,
        previous_project_context=previous_project_context,
    )
    prompt_template = {
        "final": template_metadata(FINAL_TEMPLATE_NAME, FINAL_TEMPLATE_VERSION, final_payload),
        "cover": {"templateName": COVER_TEMPLATE_NAME, "templateVersion": COVER_TEMPLATE_VERSION},
    }
    context.run_log.append(
        stage="decentralized_final_prompt_rendered",
        status="succeeded",
        input_summary="Final game prompt rendered from selected static preview.",
        output_summary=f"{FINAL_TEMPLATE_NAME}@{FINAL_TEMPLATE_VERSION} is ready.",
        metrics={**prompt_template["final"], "selectedCandidateId": selected.get("candidateId")},
    )
    context.run_log.append(
        stage="decentralized_final_started",
        status="running",
        input_summary="Decentralized final game agent is starting.",
        output_summary="The selected static direction will be converted into a playable game.",
        metrics={"selectedCandidate": _safe_candidate_metrics(selected)},
    )
    final_result = _invoke_llm(adapter, final_payload, context=context, stage="decentralized_final_llm_call", summary="Final game agent returned a package candidate.")
    parsed_output = parse_final_game(final_result.text)
    if "normalizationWarnings" in parsed_output:
        context.run_log.append(
            stage="decentralized_final_output_normalized",
            status="succeeded",
            input_summary="Final game output accepted after normalization.",
            output_summary=", ".join(str(item) for item in parsed_output.get("normalizationWarnings", []))[:500],
            metrics={"normalizationWarnings": parsed_output.get("normalizationWarnings", [])},
        )

    cover_payload = build_cover_payload(model=ai_config["model"], user_request=user_request, candidate=selected, game_output=parsed_output)
    prompt_template["cover"] = template_metadata(COVER_TEMPLATE_NAME, COVER_TEMPLATE_VERSION, cover_payload)
    context.run_log.append(
        stage="decentralized_cover_prompt_rendered",
        status="succeeded",
        input_summary="Decentralized cover prompt rendered.",
        output_summary=f"{COVER_TEMPLATE_NAME}@{COVER_TEMPLATE_VERSION} is ready.",
        metrics={**prompt_template["cover"], "selectedCandidateId": selected.get("candidateId")},
    )
    context.run_log.append(
        stage="decentralized_cover_started",
        status="running",
        input_summary="Decentralized cover agent is starting.",
        output_summary="Waiting for one durable catalog cover.",
        metrics={"selectedCandidateId": selected.get("candidateId"), "targetWidth": 1200, "targetHeight": 900},
    )
    cover_result = _invoke_llm(adapter, cover_payload, context=context, stage="decentralized_cover_llm_call", summary="Cover agent returned a candidate image.")
    cover_raw_kind = "decentralized_cover"
    cover_summary = "Decentralized cover generated."
    try:
        cover_artifact = parse_cover_artifact(cover_result.text)
        context.run_log.append(
            stage="decentralized_cover_generated",
            status="succeeded",
            input_summary="Decentralized cover output parsed.",
            output_summary="Cover asset is ready for MinIO upload.",
            metrics={
                "contentType": cover_artifact.content_type,
                "sizeBytes": len(cover_artifact.content),
                "selectedCandidateId": selected.get("candidateId"),
            },
        )
    except Exception as exc:
        cover_artifact = _decentralized_fallback_cover(selected=selected, reason="cover_output_contract_failed")
        cover_raw_kind = "decentralized_fallback_svg"
        cover_summary = "Fallback decentralized SVG cover generated by backend."
        context.run_log.append(
            stage="decentralized_cover_degraded",
            status="succeeded",
            input_summary="Decentralized cover output was unavailable or not publishable.",
            output_summary=cover_summary,
            metrics={
                "reason": "cover_output_contract_failed",
                "error": exc.__class__.__name__,
                "message": str(exc)[:500],
                "outputChars": len(cover_result.text or ""),
                "contentType": cover_artifact.content_type,
                "sizeBytes": len(cover_artifact.content),
                "selectedCandidateId": selected.get("candidateId"),
            },
        )

    pipeline = _pipeline_from_final_output(
        prompt=user_request,
        agent_mode="decentralized",
        game_slug=game_slug,
        game_id=game_id,
        version_id=version_id,
        ai_config=ai_config,
        parsed_output=parsed_output,
        selected=selected,
        prompt_template=prompt_template,
        strategy_metadata=strategy_metadata,
        llm_metrics=final_result.metrics,
    )
    return DecentralizedFinalResult(
        pipeline=pipeline,
        cover_artifact=_cover_wrapper(cover_artifact, raw_kind=cover_raw_kind, summary=cover_summary),
        prompt_template=prompt_template,
        strategy_metadata=strategy_metadata,
        llm_metrics=final_result.metrics,
    )


def confirm_decentralized_run(
    *,
    user_id: str,
    run_id: str,
    decision: str,
    context: Any,
    job_id: str,
) -> str:
    normalized = decision.strip().lower()
    if normalized not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail={"code": "INVALID_DECENTRALIZED_DECISION", "message": "Decision must be accepted or rejected."})
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, agent_mode, status, summary, job_id
FROM create_runs
WHERE id = %s AND user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["agent_mode"] != "decentralized":
        raise HTTPException(status_code=409, detail={"code": "NOT_DECENTRALIZED_RUN", "message": "Run is not a decentralized run."})
    if normalized == "rejected":
        context.run_log.append(
            stage="decentralized_rejected",
            status="succeeded",
            input_summary="User rejected all decentralized preview candidates.",
            output_summary="Run canceled; preview logs retained for maintainer review.",
            metrics={"decision": "rejected"},
        )
        clear_decentralized_cache(run_id)
        with db_connection() as connection:
            connection.execute("UPDATE generation_jobs SET status = 'canceled', current_stage = 'decentralized_rejected', completed_at = now() WHERE id = %s", (job_id,))
            connection.execute(
                "UPDATE create_runs SET status = 'canceled', summary = summary || %s, completed_at = now() WHERE id = %s",
                (Jsonb({"phase": "decentralized_rejected", "decision": "rejected"}), run_id),
            )
        return "rejected"
    candidate_id = load_selection(run_id)
    if not candidate_id:
        raise HTTPException(status_code=409, detail={"code": "DECENTRALIZED_CANDIDATE_REQUIRED", "message": "Select a preview candidate before confirming."})
    context.run_log.append(
        stage="decentralized_confirmed",
        status="succeeded",
        input_summary="User confirmed the selected decentralized direction.",
        output_summary="Final game and cover generation can start.",
        metrics={"decision": "accepted", "selectedCandidateId": candidate_id},
    )
    with db_connection() as connection:
        connection.execute(
            "UPDATE create_runs SET summary = summary || %s WHERE id = %s",
            (Jsonb({"phase": "decentralized_final_generating", "decision": "accepted", "selectedCandidateId": candidate_id}), run_id),
        )
        connection.execute("UPDATE generation_jobs SET status = 'generating', current_stage = 'decentralized_final_generation' WHERE id = %s", (job_id,))
    return "accepted"
