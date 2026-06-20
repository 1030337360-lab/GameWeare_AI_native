from __future__ import annotations

from app.agents.multi_agent import multi_agent_contract_summary
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


class DecentralizedAgentStrategy(BaseAgentStrategy):
    name = "decentralized"
    topology = "decentralized-multi-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=steps([
                ("planner", "Peer Planner proposes game brief and acceptance criteria.", "llm.prompt_render | run_log.*", True),
                ("asset_agent", "Peer Asset agent proposes cover/input asset handling.", "storage.* | run_log.*", True),
                ("game_code_agent", "Peer GameCode agent claims and writes playable files.", "workspace.* | llm.*", True),
                ("build_agent", "Peer Build agent packages artifacts and identifies conflicts.", "workspace.* | storage.*", True),
                ("safety_agent", "Peer Safety agent validates generated package.", "safety_scan | run_log.*", True),
                ("publisher_agent", "Publisher resolves peer consensus and persists final artifacts.", "database.* | storage.*", True),
            ]),
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        return render_json_tool_final_rules(
            identity="Yahaha Decentralized Create peer agent",
            strategy_rules=[
                "Propose independent work against shared run state using Planner, Asset, GameCode, Build, Safety, and Publisher contracts.",
                "State claimed files, intended tools, and conflict risks in the final output object.",
                "Do not assume authority to merge other peer outputs.",
                "Use tools when workspace or artifact facts are needed; do not invent peer results.",
            ],
        )

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

{render_create_intent_rules(settings)}

Decentralized peer task:
Return one JSON tool call or one JSON final output.
For final output, put this peer payload inside output together with the game package fields:
{{
  "Finished": true,
  "proposal": "...",
  "claimedFiles": ["..."],
  "toolCalls": [{{"name": "...", "args": {{}}}}],
  "conflictNotes": ["..."],
  "stageContracts": {multi_agent_contract_summary()},
  "expectedContribution": "...",
  "files": [{{"path": "index.html", "content": "..."}}],
  "cover": {{"title": "...", "description": "...", "tags": ["..."]}},
  "implementationSummary": "...",
  "safetyNotes": ["..."]
}}

{render_shared_game_contract()}
"""
