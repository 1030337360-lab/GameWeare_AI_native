from __future__ import annotations

from typing import TYPE_CHECKING

from app.agents.strategies.base import (
    AgentRequestSettings,
    AgentStrategyPlan,
    BaseAgentStrategy,
    render_context_sections,
    render_create_intent_rules,
    render_shared_game_contract,
    steps,
)

if TYPE_CHECKING:
    from app.agents.graphs.llm_adapter import LLMGraphAdapter
    from app.agents.graphs.recording import LLMCallRecorder
    from app.agents.graphs.types import AgentGraphResult
    from app.agents.tools import ToolRegistry


class ReActAgentStrategy(BaseAgentStrategy):
    name = "react"
    topology = "single-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps(
                [
                    ("reason", "Analyze the next action needed for the game task.", "llm.prompt_render"),
                    ("act", "Call one allowed tool and inspect its JSON result.", "workspace.* | memory.* | test.*"),
                    ("observe", "Record tool output and decide whether to continue.", "run_log.*"),
                ]
            ),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return """You are the Yahaha ReAct Create Agent, a local game-generation coding agent working inside a bounded workspace.

Rules:
- Use tools instead of guessing about the workspace.
- Return exactly one JSON object.
- For a tool call, return {"type":"tool","tool":{"name":"tool_name","args":{...}}}.
- For a final answer, return {"type":"final","output":{"Finished":true,"files":[...],"cover":{...},"implementationSummary":"...","safetyNotes":[...]}}.
- Tool args must be non-empty and must match the declared tool metadata schema.
- Never invent tool results.
- Do not repeat the same tool call with the same arguments if it did not help.
- Before proposing edits or tests for existing code, inspect the relevant implementation through tools.
- Final output must satisfy the Yahaha game package JSON contract inside the output object.
- Final output must include Finished=true only when the complete game package is ready.
- For generated game files, prefer workspace.file_write before final output. Do not put large HTML/CSS/JS in final JSON.
- After writing files, final output may reference them as {"path":"index.html","workspacePath":"index.html"}.
- Do not include markdown fences, XML tags, secrets, or backend-only identifiers.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

ReAct task:
- Think in terms of reason -> act -> observe, but do not expose hidden reasoning.
- Choose either one valid JSON tool call or one valid JSON final output.
- If index.html content is longer than a small snippet, first call workspace.file_write with path="index.html" and the complete HTML content.
- Final output must be one JSON object with {{"type": "final", "output": {{...}}}}.
- Put {{"Finished": true}}, files, cover, implementationSummary, and safetyNotes inside output.
- In final output, prefer files entries that reference workspace files, for example {{"path": "index.html", "workspacePath": "index.html"}}.

{render_shared_game_contract()}
"""

    def run_langgraph(
        self,
        *,
        settings: AgentRequestSettings,
        model: str,
        adapter: "LLMGraphAdapter",
        registry: "ToolRegistry | None" = None,
        recorder: "LLMCallRecorder | None" = None,
    ) -> "AgentGraphResult":
        from app.agents.graphs.types import AgentGraphResult
        from app.agents.graphs.react_graph import run_react_graph

        result = run_react_graph(
            settings=settings,
            model=model,
            adapter=adapter,
            registry=registry,
            recorder=recorder,
        )
        return AgentGraphResult(
            strategy=self.name,
            topology=self.topology,
            finished=result.finished,
            finish_reason=result.finish_reason,
            iterations=result.iterations,
            final_output=result.final_output,
            tool_results=result.tool_results,
            messages=result.messages,
        )
