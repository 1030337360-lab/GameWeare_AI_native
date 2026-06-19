from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategyPlan, BaseAgentStrategy, render_context_sections, render_shared_game_contract, steps


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
- For a final answer, return {"type":"final","output":{...}}.
- Tool args must be non-empty and must match the declared tool metadata schema.
- Never invent tool results.
- Do not repeat the same tool call with the same arguments if it did not help.
- Before proposing edits or tests for existing code, inspect the relevant implementation through tools.
- Final output must satisfy the Yahaha game package JSON contract.
- Do not include markdown fences, XML tags, secrets, or backend-only identifiers.
"""

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

ReAct task:
- Think in terms of reason -> act -> observe, but do not expose hidden reasoning.
- Choose either one valid JSON tool call or one valid JSON final output.

{render_shared_game_contract()}
"""
