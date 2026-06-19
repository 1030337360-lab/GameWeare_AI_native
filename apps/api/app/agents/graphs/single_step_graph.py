from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.agents.graphs.llm_adapter import LLMGraphAdapter
from app.agents.graphs.recording import LLMCallRecorder, build_llm_call_event
from app.agents.graphs.types import AgentGraphResult
from app.agents.strategies.base import AgentRequestSettings, AgentStrategy


@dataclass
class SingleStepGraphState:
    strategy: AgentStrategy
    settings: AgentRequestSettings
    model: str
    iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    final_output: dict[str, Any] | None = None
    finished: bool = False
    finish_reason: str | None = None


class SingleStepLangGraphState(TypedDict, total=False):
    strategy: AgentStrategy
    settings: AgentRequestSettings
    model: str
    iteration: int
    messages: list[dict[str, Any]]
    final_output: dict[str, Any] | None
    finished: bool
    finish_reason: str | None


def _to_langgraph_state(state: SingleStepGraphState) -> SingleStepLangGraphState:
    return {
        "strategy": state.strategy,
        "settings": state.settings,
        "model": state.model,
        "iteration": state.iteration,
        "messages": state.messages,
        "final_output": state.final_output,
        "finished": state.finished,
        "finish_reason": state.finish_reason,
    }


def _from_langgraph_state(state: SingleStepLangGraphState | dict[str, Any]) -> SingleStepGraphState:
    return SingleStepGraphState(
        strategy=state["strategy"],
        settings=state["settings"],
        model=state["model"],
        iteration=state.get("iteration", 0),
        messages=state.get("messages", []),
        final_output=state.get("final_output"),
        finished=state.get("finished", False),
        finish_reason=state.get("finish_reason"),
    )


def _single_llm_step(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    if state.finished:
        return state

    payload = state.strategy.build_responses_payload(state.settings, state.model)
    result = adapter.invoke(payload)
    if recorder:
        recorder.record(
            build_llm_call_event(
                strategy=state.strategy.name,
                topology=state.strategy.topology,
                iteration=1,
                output_text=result.text,
                metrics=result.metrics,
                raw=result.raw,
            )
        )
    state.messages.append({"iteration": 1, "text": result.text, "raw": result.raw, "metrics": result.metrics})
    state.final_output = {"text": result.text, "raw": result.raw}
    state.iteration = 1
    state.finished = True
    state.finish_reason = "single_step_completed"
    return state


def _run_fallback_graph(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    return _single_llm_step(state, adapter, recorder)


def _run_langgraph_if_available(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return _run_fallback_graph(state, adapter, recorder)

    try:
        def node(current: SingleStepLangGraphState) -> SingleStepLangGraphState:
            return _to_langgraph_state(_single_llm_step(_from_langgraph_state(current), adapter, recorder))

        graph = StateGraph(SingleStepLangGraphState)
        graph.add_node("llm", node)
        graph.set_entry_point("llm")
        graph.add_edge("llm", END)
        app = graph.compile()
        result = app.invoke(_to_langgraph_state(state))
    except Exception:
        return _run_fallback_graph(state, adapter, recorder)

    return _from_langgraph_state(result)


def run_single_step_graph(
    *,
    strategy: AgentStrategy,
    settings: AgentRequestSettings,
    model: str,
    adapter: LLMGraphAdapter,
    recorder: LLMCallRecorder | None = None,
) -> AgentGraphResult:
    final_state = _run_langgraph_if_available(
        SingleStepGraphState(strategy=strategy, settings=settings, model=model),
        adapter,
        recorder,
    )
    return AgentGraphResult(
        strategy=strategy.name,
        topology=strategy.topology,
        finished=final_state.finished,
        finish_reason=final_state.finish_reason or "unknown",
        iterations=final_state.iteration,
        final_output=final_state.final_output,
        messages=final_state.messages,
    )
