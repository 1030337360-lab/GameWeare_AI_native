from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, render_shared_game_contract, steps


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
        return """You are the Yahaha Plan Create Agent.

Rules:
- Produce a compact structured plan for creating the game package.
- Do not execute tools in this strategy response.
- The plan must name intended tool families and validation checks.
- Keep backend-only routing data out of the prompt and output.
- Return structured JSON only. Do not include markdown fences.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

Plan task:
Return a JSON object with:
{{
  "plan": [{{"step": "...", "toolFamily": "...", "expectedOutput": "..."}}],
  "risks": ["..."],
  "acceptanceChecks": ["..."]
}}

The final implemented game package must later satisfy:
{render_shared_game_contract()}
"""
