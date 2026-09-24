from __future__ import annotations

from app.agents.strategies.base import AgentRequestSettings, AgentStrategy
from app.agents.strategies.chat import ChatAgentStrategy
from app.agents.strategies.decentralized import DecentralizedAgentStrategy
from app.agents.strategies.plan import PlanAgentStrategy
from app.agents.strategies.react import ReActAgentStrategy
from app.agents.strategies.refine import RefineAgentStrategy


STRATEGY_REGISTRY: dict[str, AgentStrategy] = {
    "chat": ChatAgentStrategy(),
    "react": ReActAgentStrategy(),
    "plan": PlanAgentStrategy(),
    "refine": RefineAgentStrategy(),
    "decentralized": DecentralizedAgentStrategy(),
}


def list_agent_strategies() -> list[str]:
    return sorted(STRATEGY_REGISTRY)


def select_agent_strategy(settings: AgentRequestSettings) -> AgentStrategy:
    normalized_mode = (settings.agent_mode or "chat").strip().lower()
    normalized_create_type = (settings.create_type or "init").strip().lower()
    if normalized_mode in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[normalized_mode]
    if normalized_mode in {"opt"}:
        return STRATEGY_REGISTRY["refine"]
    if normalized_mode in {"init"}:
        return STRATEGY_REGISTRY["chat"]
    if normalized_mode in {"multi"}:
        return STRATEGY_REGISTRY["decentralized"]
    if normalized_create_type == "opt":
        return STRATEGY_REGISTRY["refine"]
    return STRATEGY_REGISTRY["chat"]
