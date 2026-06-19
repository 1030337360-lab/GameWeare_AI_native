from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, render_shared_game_contract, steps


class RefineAgentStrategy(BaseAgentStrategy):
    name = "refine"
    topology = "single-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("inspect", "Inspect the existing project and latest run state.", "database.* | storage.*"),
                    ("refine", "Apply targeted changes using workspace-safe tools.", "workspace.* | llm.prompt_render"),
                    ("compare", "Compare the refined result with the previous baseline.", "test.* | run_log.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return """You are the Yahaha Refine Create Agent.

Rules:
- Improve an existing generated game with the smallest coherent change.
- Use provided context and tools; do not assume hidden project state.
- Prefer preserving working behavior over broad rewrites.
- Return structured JSON only. Do not include markdown fences.
- Do not include secrets or backend-only identifiers.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

Refine task:
Return a JSON object with the updated game package or a concise refinement proposal.
Prioritize targeted improvements, compatibility with the current iframe runtime, and verifiable changes.

{render_shared_game_contract()}
"""
