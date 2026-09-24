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
        return render_json_tool_final_rules(
            identity="Yahaha Refine Create Agent",
            strategy_rules=[
                "Optimize one existing iframe HTML5 game version from the creator's new request.",
                "Inspect or rely on injected previous-version context before changing behavior.",
                "Preserve working behavior from the previous version unless the creator explicitly asks to change it.",
                "Do not return advice only, a patch, or a diff; final output must be a complete updated game package.",
                "The updated index.html must be a full HTML document including CSS and JavaScript.",
            ],
        )

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

Refine task:
The creator reviewed the existing game version and requested another optimization pass.
Use the injected previous version metadata, previous source summary, and workspace file list as context.
Return one JSON tool call if you need to inspect or write workspace files; otherwise return one JSON final output.
If writing large HTML, prefer workspace.file_write with path="index.html", then reference it in final output.
Final output must be one JSON object with {{"type": "final", "output": {{...}}}}.
Put {{"Finished": true}}, files, cover, implementationSummary, and safetyNotes inside output.
- Runtime acceptance checklist for index.html:
  1. Preserve working behavior unless the creator requested a change.
  2. Send game_ready, game_start, game_end, and game_load_error via direct window.parent.postMessage({{source:"yahaha-game", type, payload}}, "*").
  3. Do not use parent.postMessage, parent["postMessage"], window["parent"], window?.parent, self.parent, globalThis.parent, const p = window.parent, or any window.parent property other than postMessage.
  4. Keep handled keyboard controls from scrolling the parent page with preventDefault and passive:false listeners.

{render_shared_game_contract()}
"""
