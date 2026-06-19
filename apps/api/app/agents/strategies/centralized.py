from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, render_shared_game_contract, steps


class CentralizedAgentStrategy(BaseAgentStrategy):
    name = "centralized"
    topology = "centralized-multi-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("main_agent_plan", "A main agent creates the task graph and assigns sub-agent work.", "llm.prompt_render"),
                    ("sub_agent_execute", "Specialized sub-agents execute assigned JSON tool calls.", "workspace.* | command.*"),
                    ("main_agent_merge", "The main agent merges outputs and writes the run summary.", "run_log.* | storage.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return """You are the Yahaha Centralized Multi-Agent Coordinator.

Rules:
- Act as the main agent that plans, assigns, and merges sub-agent work.
- Do not execute sub-agent work in this response.
- Output the task graph, sub-agent roles, dependencies, merge policy, and final package constraints.
- Return structured JSON only. Do not include markdown fences.
- Do not include secrets or backend-only identifiers.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

Centralized coordination task:
Return a JSON object with:
{{
  "taskGraph": [{{"id": "...", "role": "...", "dependsOn": [], "toolFamilies": []}}],
  "subAgentRoles": [{{"name": "...", "responsibility": "..."}}],
  "mergePolicy": "...",
  "finalOutputContract": "Yahaha game package JSON"
}}

{render_shared_game_contract()}
"""
