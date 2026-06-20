from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from app.agents.graphs.llm_adapter import LLMGraphAdapter
from app.agents.graphs.errors import LLMProviderCallError, provider_error_diagnostics
from app.agents.graphs.recording import LLMCallRecorder, build_llm_call_event
from app.agents.graphs.types import AgentGraphResult
from app.agents.strategies.base import AgentRequestSettings, AgentStrategy
from app.agents.tools.registry import ToolRegistry

MAX_SINGLE_STEP_ITERATIONS = 4


@dataclass
class SingleStepGraphState:
    strategy: AgentStrategy
    settings: AgentRequestSettings
    model: str
    iteration: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    final_output: dict[str, Any] | None = None
    finished: bool = False
    finish_reason: str | None = None


class SingleStepLangGraphState(TypedDict, total=False):
    strategy: AgentStrategy
    settings: AgentRequestSettings
    model: str
    iteration: int
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
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
        "tool_results": state.tool_results,
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
        tool_results=state.get("tool_results", []),
        final_output=state.get("final_output"),
        finished=state.get("finished", False),
        finish_reason=state.get("finish_reason"),
    )


def _truncate(value: Any, limit: int = 700) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:limit]


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
        return {"type": "legacy_text", "raw": text}
    return payload if isinstance(payload, dict) else {"type": "legacy_json", "raw": payload}


def _is_finished(payload: dict[str, Any]) -> bool:
    if payload.get("Finished") is True or payload.get("finished") is True:
        return True
    output = payload.get("output")
    if isinstance(output, dict):
        return output.get("Finished") is True or output.get("finished") is True
    return False


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
    if data:
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
        elif isinstance(parsed, dict) and parsed.get("type") in {"legacy_text", "legacy_json"}:
            item["legacyResponse"] = True
        summarized.append(item)
    return summarized


def _tool_results_for_prompt(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_summarize_tool_result_for_prompt(result) for result in tool_results[-4:]]


def _build_iteration_payload(state: SingleStepGraphState) -> dict[str, Any]:
    payload = state.strategy.build_responses_payload(state.settings, state.model)
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
                                    "Continue from these compact observations. "
                                    "Return exactly one JSON tool call or one final output. "
                                    "Use Finished=true only when the required strategy output is ready."
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
    state: SingleStepGraphState,
    result: Any,
    recorder: LLMCallRecorder | None,
    *,
    iteration: int,
) -> None:
    if not recorder:
        return
    recorder.record(
        build_llm_call_event(
            strategy=state.strategy.name,
            topology=state.strategy.topology,
            iteration=iteration,
            output_text=result.text,
            metrics=result.metrics,
            raw=result.raw,
        )
    )


def _apply_parsed_response(
    state: SingleStepGraphState,
    parsed: dict[str, Any],
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None,
    *,
    iteration: int,
) -> SingleStepGraphState:
    if _is_finished(parsed):
        state.finished = True
        state.finish_reason = "finished"
        output = parsed.get("output")
        state.final_output = output if isinstance(output, dict) else parsed
        return state

    if parsed.get("type") == "tool":
        tool_result = _run_tool_call(registry, parsed)
        state.tool_results.append(tool_result)
        if recorder:
            request_summary, files = _summarize_tool_payload(parsed)
            recorder.record_tool_call(
                {
                    "kind": "tool_call",
                    "strategy": state.strategy.name,
                    "topology": state.strategy.topology,
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
        return state

    state.finished = True
    state.finish_reason = "single_step_completed"
    last_message = state.messages[-1] if state.messages else {}
    state.final_output = {
        "text": last_message.get("text", ""),
        "raw": last_message.get("raw", {}),
    }
    return state


def _single_llm_step(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    if state.finished or state.iteration >= MAX_SINGLE_STEP_ITERATIONS:
        state.finished = True
        state.finish_reason = state.finish_reason or "max_iterations"
        return state

    iteration = state.iteration + 1
    payload = _build_iteration_payload(state)
    result = adapter.invoke(payload)
    _record_llm_result(state, result, recorder, iteration=iteration)
    provider_error = provider_error_diagnostics(result.raw)
    if provider_error:
        state.messages.append(
            {
                "iteration": iteration,
                "text": result.text,
                "parsed": {"type": "provider_error", "error": provider_error},
                "raw": result.raw,
                "metrics": result.metrics,
                "providerError": provider_error,
            }
        )
        state.final_output = {"Finished": False, "error": provider_error}
        state.iteration = iteration
        state.finished = True
        state.finish_reason = "provider_error"
        raise LLMProviderCallError(provider_error)

    parsed = _parse_llm_json(result.text)
    state.messages.append({"iteration": iteration, "text": result.text, "parsed": parsed, "raw": result.raw, "metrics": result.metrics})
    _apply_parsed_response(state, parsed, registry, recorder, iteration=iteration)

    state.iteration = iteration
    if not state.finished and state.iteration >= MAX_SINGLE_STEP_ITERATIONS:
        state.finished = True
        state.finish_reason = "max_iterations"
    return state


def _run_fallback_graph(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    while not state.finished:
        state = _single_llm_step(state, adapter, registry, recorder)
    return state


def _run_langgraph_if_available(
    state: SingleStepGraphState,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry,
    recorder: LLMCallRecorder | None = None,
) -> SingleStepGraphState:
    try:
        from langgraph.graph import END, StateGraph
    except Exception:
        return _run_fallback_graph(state, adapter, registry, recorder)

    try:
        def node(current: SingleStepLangGraphState) -> SingleStepLangGraphState:
            return _to_langgraph_state(_single_llm_step(_from_langgraph_state(current), adapter, registry, recorder))

        def route(current: SingleStepLangGraphState) -> str:
            return "done" if current.get("finished") else "loop"

        graph = StateGraph(SingleStepLangGraphState)
        graph.add_node("llm", node)
        graph.set_entry_point("llm")
        graph.add_conditional_edges("llm", route, {"loop": "llm", "done": END})
        app = graph.compile()
        result = app.invoke(_to_langgraph_state(state))
    except LLMProviderCallError:
        raise
    except Exception:
        return _run_fallback_graph(state, adapter, registry, recorder)

    return _from_langgraph_state(result)


def run_single_step_graph(
    *,
    strategy: AgentStrategy,
    settings: AgentRequestSettings,
    model: str,
    adapter: LLMGraphAdapter,
    registry: ToolRegistry | None = None,
    recorder: LLMCallRecorder | None = None,
) -> AgentGraphResult:
    from app.agents.tools import build_builtin_tool_registry

    final_state = _run_langgraph_if_available(
        SingleStepGraphState(strategy=strategy, settings=settings, model=model),
        adapter,
        registry or build_builtin_tool_registry(),
        recorder,
    )
    return AgentGraphResult(
        strategy=strategy.name,
        topology=strategy.topology,
        finished=final_state.finished,
        finish_reason=final_state.finish_reason or "unknown",
        iterations=final_state.iteration,
        final_output=final_state.final_output,
        tool_results=final_state.tool_results,
        messages=final_state.messages,
    )
