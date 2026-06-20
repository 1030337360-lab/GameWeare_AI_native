from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, steps


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

Your job is to optimize one existing iframe HTML5 game version from the creator's new request.

Hard output rules:
- Return only the complete updated HTML document.
- Do not return JSON.
- Do not return markdown fences.
- Do not return a partial patch, diff, explanation, manifest, source metadata, or backend fields.
- The HTML must be the full global game code for index.html, including <!doctype html>, <html>, <head>, <body>, CSS, and JavaScript.
- Preserve working behavior from the previous version unless the creator explicitly asks to change it.
- Use the previous version context injected by the backend as the baseline; the backend will package manifest.json and source.json automatically.
- The game must run inside a sandboxed iframe with scripts only.
- Do not use remote scripts, eval, new Function, document.cookie, localStorage, sessionStorage, IndexedDB, network APIs, Web Workers, pointer lock, file APIs, or parent DOM access.
- Use Canvas or DOM APIs available inside the iframe.
- Handle keyboard input with preventDefault for gameplay keys so the parent page does not scroll.
- Keep the system cursor visible and do not hide or replace it.
- Send postMessage events for game_ready, game_start, game_end, and game_load_error when appropriate.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

Refine task:
The creator reviewed the existing game version and requested another optimization pass.
Use the injected previous version metadata, previous source summary, and workspace file list as context.

Output requirement:
Return exactly one complete updated HTML document for index.html. Nothing else.
"""
