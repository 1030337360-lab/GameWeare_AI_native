from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.agents.graphs.llm_adapter import LLMGraphAdapter
from app.agents.graphs.errors import LLMProviderCallError, provider_error_diagnostics
from app.agents.graphs.recording import LLMCallRecorder, build_llm_call_event
from app.agents.strategies.base import AgentRequestSettings
from app.agents.strategies.registry import select_agent_strategy
from app.agents.tools.registry import ToolRegistry

MAX_REACT_ITERATIONS = 4
RECOVERY_USER_REQUEST_LIMIT = 6000
RECOVERY_TOOL_METADATA_LIMIT = 24


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


def _truncate(value: Any, limit: int = 700) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


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


def _summarize_tool_result_for_prompt(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    error = result.get("error") if isinstance(result.get("error"), dict) else None
    summary: dict[str, Any] = {
        "ok": result.get("ok") is True,
        "responseSummary": _summarize_tool_result(result),
    }
    if isinstance(data, dict):
        summary["dataKeys"] = list(data.keys())[:12]
        if isinstance(data.get("path"), str):
            summary["path"] = data["path"]
        if isinstance(data.get("files"), list):
            summary["files"] = [str(item) for item in data["files"][:80]]
            summary["total"] = data.get("total", len(data["files"]))
            summary["truncated"] = bool(data.get("truncated"))
        if isinstance(data.get("content"), str):
            summary["contentPrefix"] = data["content"][:2000]
            summary["contentChars"] = len(data["content"])
        for key in ("bytes", "sha256", "written", "count", "tags", "summary"):
            if key in data:
                summary[key] = data[key]
    if error:
        summary["error"] = {
            "code": error.get("code"),
            "message": _truncate(error.get("message") or error, 700),
            "type": error.get("type"),
            "files": error.get("files") if isinstance(error.get("files"), list) else [],
        }
    return summary


def _tool_call_for_prompt(parsed: dict[str, Any]) -> dict[str, Any]:
    tool = parsed.get("tool") if isinstance(parsed.get("tool"), dict) else {}
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    summarized_args = dict(args)
    if isinstance(summarized_args.get("content"), str):
        summarized_args["contentPrefix"] = summarized_args["content"][:1000]
        summarized_args["contentChars"] = len(summarized_args["content"])
        summarized_args.pop("content", None)
    return {
        "type": "tool",
        "tool": {
            "name": tool.get("name"),
            "args": summarized_args,
        },
    }


def _messages_for_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for message in messages[-4:]:
        parsed = message.get("parsed") if isinstance(message.get("parsed"), dict) else {}
        item: dict[str, Any] = {
            "iteration": message.get("iteration"),
            "responseType": parsed.get("type") if isinstance(parsed, dict) else None,
            "outputPreview": _truncate(message.get("text", ""), 900),
        }
        if isinstance(parsed, dict) and parsed.get("type") == "tool":
            item["toolCall"] = _tool_call_for_prompt(parsed)
        elif isinstance(parsed, dict) and parsed.get("type") == "invalid":
            item["error"] = parsed.get("error")
        summarized.append(item)
    return summarized


def _tool_results_for_prompt(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_summarize_tool_result_for_prompt(result) for result in tool_results[-4:]]


def _tool_calls_for_recovery(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for message in messages[-4:]:
        parsed = message.get("parsed") if isinstance(message.get("parsed"), dict) else {}
        if parsed.get("type") == "tool":
            calls.append(_tool_call_for_prompt(parsed))
    return calls


def _tool_metadata_for_recovery(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for tool in tools[:RECOVERY_TOOL_METADATA_LIMIT]:
        if not isinstance(tool, dict):
            continue
        compact.append(
            {
                "name": tool.get("name"),
                "summary": _truncate(tool.get("summary", ""), 240),
                "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
            }
        )
    return compact


def _build_recovery_payload(state: ReActGraphState, provider_error: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": state.model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are the Yahaha ReAct Recovery Agent. A prior ReAct continuation call failed at the provider layer. "
                            "Use only the compact observations supplied here. Return exactly one JSON object: either "
                            "{\"type\":\"tool\",\"tool\":{\"name\":\"tool_name\",\"args\":{...}}} or "
                            "{\"type\":\"final\",\"output\":{\"Finished\":true,\"files\":[...],\"cover\":{...},"
                            "\"implementationSummary\":\"...\",\"safetyNotes\":[...]}}. "
                            "Prefer a final output if enough information is available. Do not include markdown, full logs, secrets, or backend IDs."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(
                            {
                                "createRequestPrefix": _truncate(state.settings.user_request, RECOVERY_USER_REQUEST_LIMIT),
                                "createRequestChars": len(state.settings.user_request),
                                "workspaceCapability": state.settings.workspace_capability,
                                "workspaceBoundary": state.settings.workspace_boundary,
                                "providerErrorSummary": {
                                    "code": provider_error.get("code"),
                                    "message": _truncate(provider_error.get("message", ""), 500),
                                    "statusCode": provider_error.get("statusCode"),
                                    "attempt": provider_error.get("attempt"),
                                    "attempts": provider_error.get("attempts"),
                                },
                                "recentToolCalls": _tool_calls_for_recovery(state.messages),
                                "toolResults": _tool_results_for_prompt(state.tool_results),
                                "availableToolMetadata": _tool_metadata_for_recovery(state.settings.tool_metadata),
                                "instruction": (
                                    "Recover from the provider error using these summaries. "
                                    "Return one final game package if possible. If one more workspace action is truly required, return exactly one valid tool call."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            },
        ],
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 25000,
    }


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
                                "previousMessages": _messages_for_prompt(state.messages),
                                "toolResults": _tool_results_for_prompt(state.tool_results),
                                "instruction": (
                                    "Continue the ReAct loop from these summarized observations. "
                                    "Return exactly one JSON tool call or one final output. "
                                    "Use Finished=true only when the complete game package is ready."
                                ),
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


def _record_llm_result(
    state: ReActGraphState,
    result: Any,
    recorder: LLMCallRecorder | None = None,
    *,
    iteration: int,
    recovery: bool = False,
) -> None:
    if not recorder:
        return
    metrics = dict(result.metrics) if isinstance(result.metrics, dict) else {}
    if recovery:
        metrics["reactRecovery"] = True
    event = build_llm_call_event(
        strategy=state.strategy_name,
        topology=f"{state.topology}-recovery" if recovery else state.topology,
        iteration=iteration,
        output_text=result.text,
        metrics=metrics,
        raw=result.raw,
    )
    if recovery:
        event["recovery"] = True
    recorder.record(event)


def _apply_parsed_response(
    state: ReActGraphState,
    parsed: dict[str, Any],
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None,
    *,
    iteration: int,
    recovered: bool = False,
) -> ReActGraphState:
    if _is_finished(parsed):
        state.finished = True
        state.finish_reason = "recovered_after_provider_error" if recovered else "finished"
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
                    "iteration": iteration,
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
    return state


def _raise_provider_error(state: ReActGraphState, provider_error: dict[str, Any], *, iteration: int, result: Any) -> None:
    state.messages.append(
        {
            "iteration": iteration,
            "text": result.text,
            "parsed": {"type": "provider_error", "error": provider_error},
            "raw": result.raw,
            "metrics": result.metrics,
        }
    )
    state.iteration += 1
    state.finished = True
    state.finish_reason = "provider_error"
    state.final_output = {"Finished": False, "error": provider_error}
    raise LLMProviderCallError(provider_error)


def _recover_from_provider_error(
    state: ReActGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None,
    *,
    provider_error: dict[str, Any],
    iteration: int,
) -> ReActGraphState:
    recovery_result = adapter.invoke(_build_recovery_payload(state, provider_error))
    _record_llm_result(state, recovery_result, recorder, iteration=iteration, recovery=True)
    recovery_provider_error = provider_error_diagnostics(recovery_result.raw)
    if recovery_provider_error:
        diagnostics = {
            "ok": False,
            "code": "react_recovery_provider_error",
            "message": "The LLM provider call failed during ReAct recovery.",
            "statusCode": recovery_provider_error.get("statusCode") or provider_error.get("statusCode"),
            "providerError": provider_error,
            "recoveryProviderError": recovery_provider_error,
        }
        _raise_provider_error(state, diagnostics, iteration=iteration, result=recovery_result)

    parsed = _parse_llm_json(recovery_result.text)
    state.messages.append(
        {
            "iteration": iteration,
            "text": recovery_result.text,
            "parsed": parsed,
            "raw": recovery_result.raw,
            "metrics": recovery_result.metrics,
            "recoveredProviderError": provider_error,
        }
    )
    _apply_parsed_response(state, parsed, registry, recorder, iteration=iteration, recovered=True)
    state.iteration += 1
    if not state.finished and state.iteration >= MAX_REACT_ITERATIONS:
        state.finished = True
        state.finish_reason = "max_iterations"
    return state


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

    iteration = state.iteration + 1
    result = adapter.invoke(_build_iteration_payload(state))
    _record_llm_result(state, result, recorder, iteration=iteration)
    provider_error = provider_error_diagnostics(result.raw)
    if provider_error:
        if state.tool_results:
            return _recover_from_provider_error(
                state,
                adapter,
                registry,
                recorder,
                provider_error=provider_error,
                iteration=iteration,
            )
        _raise_provider_error(state, provider_error, iteration=iteration, result=result)

    parsed = _parse_llm_json(result.text)
    state.messages.append(
        {
            "iteration": iteration,
            "text": result.text,
            "parsed": parsed,
            "raw": result.raw,
            "metrics": result.metrics,
        }
    )
    _apply_parsed_response(state, parsed, registry, recorder, iteration=iteration)

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
    except LLMProviderCallError:
        raise
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
