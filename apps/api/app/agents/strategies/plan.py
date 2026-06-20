from __future__ import annotations

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
        return render_json_tool_final_rules(
            identity="Yahaha Plan Create Agent",
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
- If this is a clean initial creation and no workspace state is needed, you may directly return final output.
- Do not output markdown fences.
"""


def _approved_plan(settings: AgentRequestSettings) -> str:
    for item in settings.persistent_memory_summary:
        if isinstance(item, dict) and item.get("memoryType") == "approved_plan":
            payload = item.get("payload")
            if isinstance(payload, str) and payload.strip():
                return payload
    return ""
