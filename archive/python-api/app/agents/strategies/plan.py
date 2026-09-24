from __future__ import annotations

import json
from typing import Any

from app.agents.strategies.base import (
    AgentRequestSettings,
    AgentStrategyPlan,
    BaseAgentStrategy,
    render_context_sections,
    render_create_intent_rules,
    render_json_tool_final_rules,
    render_shared_game_contract,
    steps,
)


def _short_text(value: Any, limit: int = 500) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


def _compact_approved_plan_payload(value: str) -> str:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return value[:6000]
    if not isinstance(payload, dict):
        return value[:6000]
    plan = payload.get("plan") if isinstance(payload.get("plan"), list) else []
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    checks = payload.get("acceptanceChecks") if isinstance(payload.get("acceptanceChecks"), list) else []
    compact = {
        "plan": [
            {
                "id": item.get("id"),
                "title": _short_text(item.get("title", ""), 140),
                "goal": _short_text(item.get("goal", ""), 260),
                "toolFamily": _short_text(item.get("toolFamily", ""), 120),
                "expectedOutput": _short_text(item.get("expectedOutput", ""), 260),
                "acceptanceCheckRefs": item.get("acceptanceCheckRefs") if isinstance(item.get("acceptanceCheckRefs"), list) else [],
            }
            for item in plan[:8]
            if isinstance(item, dict)
        ],
        "risks": [_short_text(item, 220) for item in risks[:8]],
        "acceptanceChecks": [
            {
                "id": item.get("id"),
                "description": _short_text(item.get("description", ""), 260),
                "type": _short_text(item.get("type", ""), 80),
                "severity": _short_text(item.get("severity", ""), 80),
            }
            for item in checks[:12]
            if isinstance(item, dict)
        ],
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)


class PlanAgentStrategy(BaseAgentStrategy):
    name = "plan"
    topology = "single-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("plan", "Create a structured implementation plan before generation.", "llm.prompt_render"),
                    ("execute", "Execute planned tool calls in order.", "command.* | workspace.* | storage.*"),
                    ("verify", "Summarize validation results.", "test.* | run_log.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        if not _approved_plan(settings):
            return """You are the Gameweare Plan Create Agent, a local game-planning agent working inside a bounded workspace.

Rules:
- Use tools instead of guessing about the workspace.
- Return exactly one JSON object.
- For a tool call, return {"type":"tool","tool":{"name":"tool_name","args":{...}}}.
- For a final answer, return {"type":"final","output":{"Finished":true,"plan":[...],"risks":[...],"acceptanceChecks":[...]}}.
- Tool args must be non-empty and must match the declared tool metadata schema.
- Never invent tool results.
- Do not repeat the same tool call with the same arguments if it did not help.
- This pass is plan preview only: do not generate files, cover metadata, implementationSummary, or safetyNotes.
- The plan must contain 3-8 concise steps with stable ids, intended tool families, expected outputs, and acceptance check refs.
- Risks and acceptanceChecks must be non-empty and relevant to playable iframe HTML5 games.
- Include runtime acceptance criteria for requestAnimationFrame, keyboard preventDefault with passive:false, and Gameweare lifecycle messages through direct window.parent.postMessage(...).
- The only allowed parent window reference in the later index.html is window.parent.postMessage(...).
- Never use parent.postMessage(...), parent["postMessage"](...), window["parent"], window?.parent, self.parent, globalThis.parent, or any window.parent property other than postMessage.
- Do not include markdown fences, XML tags, secrets, or backend-only identifiers.

Plan preview JSON reference:
{
  "type": "final",
  "output": {
    "Finished": true,
    "plan": [
      {
        "id": "step-1",
        "title": "Core loop",
        "goal": "Create the game loop and state model",
        "toolFamily": "workspace.*",
        "expectedOutput": "index.html will contain a requestAnimationFrame loop",
        "acceptanceCheckRefs": ["check-1"]
      }
    ],
    "risks": ["Keyboard input may scroll the parent page if preventDefault is missing"],
    "acceptanceChecks": [
      {"id": "check-1", "description": "Game loop uses requestAnimationFrame", "type": "performance", "severity": "must"}
    ]
  }
}
"""
        return render_json_tool_final_rules(
            identity="Gameweare Plan Create Agent",
            strategy_rules=[
                "Build a compact implementation plan before producing the final game package.",
                "Use tools when workspace facts are needed; do not guess file state.",
                "If no approved plan is provided, return a plan preview only: plan, risks, and acceptanceChecks.",
                "If an approved plan is provided, use it to produce the completed game package fields.",
                "The plan must name intended tool families and validation checks.",
            ],
        )

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        approved_plan = _approved_plan(settings)
        if approved_plan:
            return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

Approved plan:
{approved_plan}

Plan task:
Return one JSON tool call or one JSON final output.
The user accepted the approved plan. Generate the playable game package now.
If writing large HTML, prefer workspace.file_write with path="index.html", then reference it in final output.
Runtime acceptance checklist for index.html:
1. Use window.parent.postMessage({{"source":"gameweare-game","type":type,"payload":payload}}, "*") directly for game_ready, game_start, game_end, and game_load_error.
2. Do not use parent.postMessage, parent["postMessage"], window["parent"], window?.parent, self.parent, globalThis.parent, const p = window.parent, or any window.parent property other than postMessage.
3. Implement preventDefault with passive:false listeners for handled keyboard controls.
For final output, preserve the approved plan data and put it inside output together with the game package fields:
{{
  "Finished": true,
  "plan": [
    {{
      "id": "step-1",
      "title": "...",
      "goal": "...",
      "toolFamily": "workspace.*",
      "expectedOutput": "...",
      "acceptanceCheckRefs": ["check-1"]
    }}
  ],
  "risks": ["..."],
  "acceptanceChecks": [
    {{"id": "check-1", "description": "...", "type": "runtime", "severity": "must"}}
  ],
  "files": [{{"path": "index.html", "content": "..."}}],
  "cover": {{"title": "...", "description": "...", "tags": ["..."]}},
  "implementationSummary": "...",
  "safetyNotes": ["..."]
}}

{render_shared_game_contract()}
"""

        return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

Plan preview task:
Return one JSON tool call or one JSON final output.
For final output, return only a plan preview for user approval. Do not generate files yet.
Use this shape:
{{
  "type": "final",
  "output": {{
    "Finished": true,
    "plan": [
      {{
        "id": "step-1",
        "title": "Core loop",
        "goal": "Create the game loop and state model",
        "toolFamily": "workspace.*",
        "expectedOutput": "index.html will contain a requestAnimationFrame loop",
        "acceptanceCheckRefs": ["check-1"]
      }}
    ],
    "risks": ["Keyboard input may scroll the parent page if preventDefault is missing"],
    "acceptanceChecks": [
      {{"id": "check-1", "description": "Game loop uses requestAnimationFrame", "type": "performance", "severity": "must"}}
    ]
  }}
}}

Plan constraints:
- Keep plan to 3-8 steps.
- Use stable IDs like step-1 and check-1.
- Do not use UUIDs or backend IDs.
- If workspace state is needed, call a tool first.
- If this is a clean initial creation and no workspace state is needed, you may directly return the final plan preview output.
- The later generated index.html must use the Gameweare iframe runtime protocol and only call window.parent.postMessage directly.
- Do not output markdown fences.
"""


def _approved_plan(settings: AgentRequestSettings) -> str:
    for item in settings.persistent_memory_summary:
        if isinstance(item, dict) and item.get("memoryType") == "approved_plan":
            payload = item.get("payload")
            if isinstance(payload, str) and payload.strip():
                return _compact_approved_plan_payload(payload)
    return ""
