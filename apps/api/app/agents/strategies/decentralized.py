from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, render_shared_game_contract, steps


class DecentralizedAgentStrategy(BaseAgentStrategy):
    name = "decentralized"
    topology = "decentralized-multi-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("shared_state_init", "Initialize shared run state and workspace boundaries.", "run_log.* | storage.*"),
                    ("peer_agent_work", "Peer agents independently propose JSON tool calls against shared state.", "llm.prompt_render | workspace.*"),
                    ("consensus", "Resolve conflicts and choose the final artifact set.", "database.* | run_log.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return """You are a Yahaha Decentralized Create peer agent.

Rules:
- Propose independent work against shared run state.
- State claimed files, intended tools, and conflict risks.
- Do not assume authority to merge other peer outputs.
- Return structured JSON only. Do not include markdown fences.
- Do not include secrets or backend-only identifiers.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

Decentralized peer task:
Return a JSON object with:
{{
  "proposal": "...",
  "claimedFiles": ["..."],
  "toolCalls": [{{"name": "...", "args": {{}}}}],
  "conflictNotes": ["..."],
  "expectedContribution": "..."
}}

{render_shared_game_contract()}
"""
