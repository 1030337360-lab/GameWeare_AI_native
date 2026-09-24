from __future__ import annotations

import re
from typing import Any

from app.database import db_connection
from app.schemas import Game, ProfileActivity, ProfilePlayRecord, ProfileProjectDetail, ProfileProjectIndex, ProfileProjectRunFeedback, ProfileRunStepRecord
from app.services.catalog import get_game

SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|authorization)", re.IGNORECASE)
DATA_URL_RE = re.compile(r"data:[^;,\s]+;base64,[A-Za-z0-9+/=]+")
AUTH_HEADER_RE = re.compile(r"\bAuthorization\s*:\s*(?:Bearer|Basic)?\s*[^\s,;]+", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|apiKey|token|secret|password)\b\s*[:=]\s*['\"]?[^'\"\s,;}]+['\"]?",
    re.IGNORECASE,
)
SENSITIVE_WORD_RE = re.compile(r"\b(api[_-]?key|apiKey|authorization|token|secret|password)\b", re.IGNORECASE)
SAFE_METRIC_KEYS = {
    "completionTokens",
    "outputTokens",
    "promptTokens",
    "totalTokens",
    "tokenUsage",
}
LONG_TEXT_LIMIT = 1800
SUMMARY_TEXT_LIMIT = 900


def _summary_20_words(text: str) -> str:
    tokens = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]|[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", text or "")
    if not tokens:
        return ""
    summary = " ".join(tokens[:20])
    return summary + ("..." if len(tokens) > 20 else "")


def _truncate_text(value: str, limit: int = LONG_TEXT_LIMIT) -> str:
    cleaned = DATA_URL_RE.sub("[redacted-base64]", value)
    cleaned = AUTH_HEADER_RE.sub("[redacted-secret]", cleaned)
    cleaned = SECRET_ASSIGNMENT_RE.sub("[redacted-secret]", cleaned)
    cleaned = SENSITIVE_WORD_RE.sub("[redacted]", cleaned)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "... [truncated]"


def _sanitize_metric(value: Any, key: str = "") -> Any:
    if key not in SAFE_METRIC_KEYS and SENSITIVE_KEY_RE.search(key):
        return "[redacted]"
    if key in {"image_url", "imageUrl"}:
        return "[redacted-image]"
    if isinstance(value, dict):
        return {str(child_key): _sanitize_metric(child_value, str(child_key)) for child_key, child_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_metric(item, key) for item in value[:50]]
    if isinstance(value, str):
        if value.startswith("data:") or DATA_URL_RE.search(value):
            return "[redacted-base64]"
        return _truncate_text(value)
    return value


def _sanitize_summary(value: str | None) -> str | None:
    if value is None:
        return None
    return _truncate_text(value, SUMMARY_TEXT_LIMIT)


def _record_type(stage: str, status: str) -> str:
    if stage in {"llm_call", "cover_llm_call"}:
        return "llm"
    if stage == "tool_call":
        return "tool"
    if status == "failed" or stage in {"run_failed", "job_failed", "llm_generation_failed", "prompt_render_failed"}:
        return "error"
    if stage in {"run_created", "ai_config_validated", "job_created", "prompt_rendered"}:
        return "conversation"
    return "lifecycle"


def _step_from_row(row: dict[str, Any]) -> ProfileRunStepRecord:
    stage = row["stage"]
    status = row["status"]
    return ProfileRunStepRecord(
        stepNo=row["step_no"],
        stage=stage,
        status=status,
        inputSummary=_sanitize_summary(row["input_summary"]),
        outputSummary=_sanitize_summary(row["output_summary"]),
        metrics=_sanitize_metric(row["metrics"] if isinstance(row["metrics"], dict) else {}),
        createdAt=row["created_at"],
        recordType=_record_type(stage, status),  # type: ignore[arg-type]
    )


def _project_index_from_row(row: dict[str, Any]) -> ProfileProjectIndex:
    return ProfileProjectIndex(
        projectId=str(row["project_id"]),
        title=row["title"],
        status=row["status"],
        gameId=str(row["game_id"]) if row["game_id"] else None,
        gameSlug=row["game_slug"],
        latestRunId=str(row["latest_run_id"]) if row["latest_run_id"] else None,
        latestRunStatus=row["latest_run_status"],
        updatedAt=row["updated_at"],
    )


def _project_index_query() -> str:
    return """
SELECT
  p.id AS project_id,
  p.title,
  p.status,
  p.game_id,
  CASE WHEN g.deleted_at IS NULL THEN g.slug ELSE NULL END AS game_slug,
  latest.id AS latest_run_id,
  latest.status AS latest_run_status,
  p.updated_at
FROM agent_projects p
LEFT JOIN games g ON g.id = p.game_id
LEFT JOIN LATERAL (
  SELECT id, status
  FROM create_runs
  WHERE project_id = p.id
  ORDER BY created_at DESC
  LIMIT 1
) latest ON true
WHERE p.user_id = %s AND p.status <> 'deleted'
"""


def get_profile_activity(user_id: str) -> ProfileActivity:
    with db_connection() as connection:
        play_rows = connection.execute(
            """
SELECT DISTINCT ON (pe.game_id)
  pe.id AS event_id,
  pe.event_type,
  pe.created_at,
  g.slug
FROM play_events pe
JOIN games g ON g.id = pe.game_id
WHERE pe.user_id = %s AND g.publish_status = 'published' AND g.visibility = 'public' AND g.deleted_at IS NULL
ORDER BY pe.game_id, pe.created_at DESC
""",
            (user_id,),
        ).fetchall()
        project_rows = connection.execute(
            _project_index_query()
            + """
ORDER BY p.updated_at DESC
""",
            (user_id,),
        ).fetchall()

    sorted_plays = sorted(play_rows, key=lambda row: row["created_at"], reverse=True)[:3]
    recent_plays: list[ProfilePlayRecord] = []
    for row in sorted_plays:
        game = get_game(row["slug"], user_id=user_id)
        if not game:
            continue
        recent_plays.append(
            ProfilePlayRecord(
                eventId=str(row["event_id"]),
                eventType=row["event_type"],
                playedAt=row["created_at"],
                game=game,
            )
        )

    return ProfileActivity(
        recentPlays=recent_plays,
        projects=[_project_index_from_row(row) for row in project_rows],
    )


def get_profile_project_detail(user_id: str, project_id: str) -> ProfileProjectDetail | None:
    with db_connection() as connection:
        project_row = connection.execute(
            _project_index_query()
            + """
  AND p.id = %s
LIMIT 1
""",
            (user_id, project_id),
        ).fetchone()
        if not project_row:
            return None
        run_rows = connection.execute(
            """
SELECT
  r.id,
  r.job_id,
  r.status,
  r.create_type,
  r.agent_mode,
  r.created_at,
  r.completed_at,
  gj.prompt,
  COALESCE(
    string_agg(
      NULLIF(concat_ws(E'\n', crs.input_summary, crs.output_summary), ''),
      E'\n\n'
      ORDER BY crs.step_no
    ) FILTER (WHERE crs.stage IN ('llm_call', 'cover_llm_call', 'llm_generation_completed', 'run_completed')),
    ''
  ) AS llm_feedback
FROM create_runs r
LEFT JOIN generation_jobs gj ON gj.id = r.job_id
LEFT JOIN create_run_steps crs ON crs.run_id = r.id
WHERE r.project_id = %s AND r.user_id = %s
GROUP BY r.id, gj.prompt
ORDER BY r.created_at DESC
""",
            (project_id, user_id),
        ).fetchall()
        run_ids = [row["id"] for row in run_rows]
        step_rows = []
        if run_ids:
            step_rows = connection.execute(
                """
SELECT run_id, step_no, stage, status, input_summary, output_summary, metrics, created_at
FROM create_run_steps
WHERE run_id = ANY(%s::uuid[])
ORDER BY run_id, step_no ASC
""",
                (run_ids,),
            ).fetchall()

    project = _project_index_from_row(project_row)
    game: Game | None = get_game(project.gameSlug, user_id=user_id) if project.gameSlug else None
    steps_by_run: dict[str, list[ProfileRunStepRecord]] = {}
    for row in step_rows:
        steps_by_run.setdefault(str(row["run_id"]), []).append(_step_from_row(row))
    runs = [
        ProfileProjectRunFeedback(
            runId=str(row["id"]),
            jobId=str(row["job_id"]) if row["job_id"] else None,
            status=row["status"],
            createType=row["create_type"],
            agentMode=row["agent_mode"],
            promptSummary=_summary_20_words(_truncate_text(row["prompt"] or "")),
            promptFull=_sanitize_summary(row["prompt"] or "") or "",
            llmSummary=_summary_20_words(_truncate_text(row["llm_feedback"] or "")),
            llmFull=_sanitize_summary(row["llm_feedback"] or "") or "",
            createdAt=row["created_at"],
            completedAt=row["completed_at"],
            steps=steps_by_run.get(str(row["id"]), []),
        )
        for row in run_rows
    ]
    return ProfileProjectDetail(project=project, game=game, runs=runs)
