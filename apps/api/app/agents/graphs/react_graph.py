from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.agents.graphs.llm_adapter import LLMGraphAdapter
from app.agents.graphs.recording import LLMCallRecorder, build_llm_call_event
from app.agents.strategies.base import AgentRequestSettings
from app.agents.strategies.registry import select_agent_strategy
from app.agents.tools.registry import ToolRegistry

MAX_REACT_ITERATIONS = 4


@dataclass
class ReActGraphState:
    settings: AgentRequestSettings
    model: str
    iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    final_output: dict[str, Any] | None = None
    finished: bool = False
    finish_reason: str | None = None
    strategy_name: str = "react"
    topology: str = "single-agent"


@dataclass(frozen=True)
class ReActGraphResult:
    finished: bool
    finish_reason: str
    iterations: int
    final_output: dict[str, Any] | None
    tool_results: list[dict[str, Any]]
    messages: list[dict[str, Any]]


class ReActLangGraphState(TypedDict, total=False):
    settings: AgentRequestSettings
    model: str
    iteration: int
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    final_output: dict[str, Any] | None
    finished: bool
    finish_reason: str | None
    strategy_name: str
    topology: str


def _to_langgraph_state(state: ReActGraphState) -> ReActLangGraphState:
    return {
        "settings": state.settings,
        "model": state.model,
        "iteration": state.iteration,
        "messages": state.messages,
        "tool_results": state.tool_results,
        "final_output": state.final_output,
        "finished": state.finished,
        "finish_reason": state.finish_reason,
        "strategy_name": state.strategy_name,
        "topology": state.topology,
    }


def _from_langgraph_state(state: ReActLangGraphState | dict[str, Any]) -> ReActGraphState:
    return ReActGraphState(
        settings=state["settings"],
        model=state["model"],
        iteration=state.get("iteration", 0),
        messages=state.get("messages", []),
        tool_results=state.get("tool_results", []),
        final_output=state.get("final_output"),
        finished=state.get("finished", False),
        finish_reason=state.get("finish_reason"),
        strategy_name=state.get("strategy_name", "react"),
        topology=state.get("topology", "single-agent"),
    )


def _extract_json_text(text: str) -> str:
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL)
    if fence:
        return fence.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def _parse_llm_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(_extract_json_text(text))
    except json.JSONDecodeError:
        return {"type": "invalid", "error": "invalid_json", "raw": text}
    return payload if isinstance(payload, dict) else {"type": "invalid", "error": "non_object_json", "raw": payload}


def _is_finished(payload: dict[str, Any]) -> bool:
    if payload.get("Finished") is True:
        return True
    if payload.get("finished") is True:
        return True
    output = payload.get("output")
    if isinstance(output, dict):
        return output.get("Finished") is True or output.get("finished") is True
    return False


def _build_iteration_payload(state: ReActGraphState) -> dict[str, Any]:
    strategy = select_agent_strategy(state.settings)
    payload = strategy.build_responses_payload(state.settings, state.model)
    if state.messages or state.tool_results:
        payload = {**payload}
        payload["input"] = [
            *payload["input"],
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "previousMessages": state.messages[-4:],
                                "toolResults": state.tool_results[-4:],
                                "instruction": "Continue the ReAct loop. Return one JSON tool call or final output. Use Finished=true only when done.",
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            },
        ]
    return payload


def _run_tool_call(registry: ToolRegistry, payload: dict[str, Any]) -> dict[str, Any]:
    tool = payload.get("tool")
    if not isinstance(tool, dict):
        return {"ok": False, "data": {}, "error": {"code": "INVALID_TOOL_CALL", "message": "Missing tool object."}}
    name = tool.get("name")
    args = tool.get("args")
    if not isinstance(name, str) or not isinstance(args, dict) or not args:
        return {
            "ok": False,
            "data": {},
            "error": {
                "code": "INVALID_TOOL_CALL",
                "message": "Tool call requires non-empty name and args.",
                "request": payload,
            },
        }
    return registry.call(name, args)


def _summarize_tool_payload(payload: dict[str, Any]) -> tuple[str, list[str]]:
    tool = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
    name = str(tool.get("name") or "tool")
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    files: list[str] = []
    for key in ("path", "file", "filename", "relativePath", "objectKey"):
        value = args.get(key)
        if isinstance(value, str) and value:
            files.append(value)
    value = args.get("files")
    if isinstance(value, list):
        files.extend(str(item) for item in value if isinstance(item, str))
    return f"{name} called with {len(args)} argument(s).", files[:12]


def _summarize_tool_result(result: dict[str, Any]) -> str:
    if result.get("ok") is True:
        data = result.get("data")
        if isinstance(data, dict):
            return f"Tool succeeded with fields: {', '.join(list(data.keys())[:8])}."
        return "Tool succeeded."
    error = result.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "Tool failed.")[:500]
    return "Tool failed."


def _react_step(
    state: ReActGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> ReActGraphState:
    if state.finished or state.iteration >= MAX_REACT_ITERATIONS:
        state.finished = True
        state.finish_reason = state.finish_reason or "max_iterations"
        return state

    result = adapter.invoke(_build_iteration_payload(state))
    if recorder:
        recorder.record(
            build_llm_call_event(
                strategy=state.strategy_name,
                topology=state.topology,
                iteration=state.iteration + 1,
                output_text=result.text,
                metrics=result.metrics,
                raw=result.raw,
            )
        )
    parsed = _parse_llm_json(result.text)
    state.messages.append(
        {
            "iteration": state.iteration + 1,
            "text": result.text,
            "parsed": parsed,
            "raw": result.raw,
            "metrics": result.metrics,
        }
    )

    if _is_finished(parsed):
        state.finished = True
        state.finish_reason = "finished"
        output = parsed.get("output")
        state.final_output = output if isinstance(output, dict) else parsed
    elif parsed.get("type") == "tool":
        tool_result = _run_tool_call(registry, parsed)
        state.tool_results.append(tool_result)
        if recorder:
            request_summary, files = _summarize_tool_payload(parsed)
            recorder.record_tool_call(
                {
                    "kind": "tool_call",
                    "strategy": state.strategy_name,
                    "topology": state.topology,
                    "iteration": state.iteration + 1,
                    "tool": parsed.get("tool") if isinstance(parsed.get("tool"), dict) else {},
                    "files": files,
                    "requestSummary": request_summary,
                    "responseSummary": _summarize_tool_result(tool_result),
                    "result": tool_result,
                }
            )
            tool = parsed.get("tool") if isinstance(parsed.get("tool"), dict) else {}
            if tool.get("name") == "workspace.file_write" and recorder.short_term_memory and hasattr(recorder.short_term_memory, "record_file_edit"):
                args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
                recorder.short_term_memory.record_file_edit(
                    {
                        "operation": "write",
                        "path": args.get("path"),
                        "bytes": (tool_result.get("data") or {}).get("bytes") if isinstance(tool_result.get("data"), dict) else None,
                        "sha256": (tool_result.get("data") or {}).get("sha256") if isinstance(tool_result.get("data"), dict) else None,
                        "ok": tool_result.get("ok"),
                    }
                )
    else:
        state.finished = True
        state.finish_reason = "invalid_react_response"
        state.final_output = {"Finished": True, "error": "Expected tool or final JSON.", "raw": parsed}

    state.iteration += 1
    if not state.finished and state.iteration >= MAX_REACT_ITERATIONS:
        state.finished = True
        state.finish_reason = "max_iterations"
    return state


def _run_fallback_graph(
    state: ReActGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> ReActGraphState:
    while not state.finished:
        state = _react_step(state, adapter, registry, recorder)
    return state


def _run_langgraph_if_available(
    state: ReActGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> ReActGraphState:
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return _run_fallback_graph(state, adapter, registry, recorder)

    try:
        def node(current: ReActLangGraphState) -> ReActLangGraphState:
            return _to_langgraph_state(_react_step(_from_langgraph_state(current), adapter, registry, recorder))

        def route(current: ReActLangGraphState) -> str:
            return "done" if current.get("finished") else "loop"

        graph = StateGraph(ReActLangGraphState)
        graph.add_node("react", node)
        graph.set_entry_point("react")
        graph.add_conditional_edges("react", route, {"loop": "react", "done": END})
        app = graph.compile()
        result = app.invoke(_to_langgraph_state(state))
    except Exception:
        return _run_fallback_graph(state, adapter, registry, recorder)

    return _from_langgraph_state(result)


def run_react_graph(
    *,
    settings: AgentRequestSettings,
    model: str,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry | None = None,
    recorder: LLMCallRecorder | None = None,
) -> ReActGraphResult:
    from app.agents.tools import build_builtin_tool_registry

    strategy = select_agent_strategy(settings)
    state = ReActGraphState(settings=settings, model=model, strategy_name=strategy.name, topology=strategy.topology)
    final_state = _run_langgraph_if_available(state, adapter, registry or build_builtin_tool_registry(), recorder)
    return ReActGraphResult(
        finished=final_state.finished,
        finish_reason=final_state.finish_reason or "unknown",
        iterations=final_state.iteration,
        final_output=final_state.final_output,
        tool_results=final_state.tool_results,
        messages=final_state.messages,
    )
