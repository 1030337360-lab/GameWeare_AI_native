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


class ChatAgentStrategy(BaseAgentStrategy):
    name = "chat"
    topology = "single-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("interpret", "Interpret the creator request and available context.", "llm.prompt_render"),
                    ("generate", "Produce the playable game package directly.", "workspace.* | llm.prompt_render"),
                    ("summarize", "Summarize implementation and safety notes.", "run_log.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return render_json_tool_final_rules(
            identity="Yahaha Chat Create Agent",
            strategy_rules=[
                "Keep a direct creator-chat flow focused on quickly producing a playable game package.",
                "Use tools only when workspace or previous-version facts are needed.",
                "For continue optimization, inspect or rely on the injected previous-version context before changing the game.",
                "Do not return advice only; the final answer must be a complete game package.",
            ],
        )

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

Chat task:
- Convert the creator request into one complete iframe HTML5 game package.
- Return one JSON tool call if you need workspace context; otherwise return one JSON final output.
- If writing large HTML, prefer workspace.file_write with path="index.html", then reference it in final output.
- Final output must be one JSON object with {{"type": "final", "output": {{...}}}}.
- Put {{"Finished": true}}, files, cover, implementationSummary, and safetyNotes inside output.

{render_shared_game_contract()}
"""
