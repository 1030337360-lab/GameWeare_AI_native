from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.framework.workspace import WorkspaceContext
from app.agents.graphs.llm_adapter import LLMGraphResult
from app.agents.graphs.recording import LLMCallRecorder
from app.agents.graphs.react_graph import MAX_REACT_ITERATIONS, run_react_graph
from app.agents.strategies import AgentRequestSettings, list_agent_strategies, select_agent_strategy
from app.agents.strategies.registry import STRATEGY_REGISTRY
from app.agents.tools import build_builtin_tool_registry


class FakeAdapter:
    def __init__(self, texts: list[str], metrics: dict | None = None):
        self.texts = texts
        self.metrics = metrics or {}
        self.calls: list[dict] = []

    def invoke(self, payload: dict) -> LLMGraphResult:
        self.calls.append(payload)
        index = min(len(self.calls) - 1, len(self.texts) - 1)
        return LLMGraphResult(text=self.texts[index], raw={"mock": True, "index": index}, metrics=self.metrics)


class MemorySpy:
    def __init__(self) -> None:
        self.history: list[dict] = []
        self.llm_calls: list[dict] = []
        self.run_log: list[dict] = []

    def append_history(self, role: str, content: str, metadata: dict | None = None) -> None:
        self.history.append({"role": role, "content": content, "metadata": metadata or {}})

    def record_llm_call(self, payload: dict) -> None:
        self.llm_calls.append(payload)

    def append_llm_call(self, payload: dict) -> dict:
        self.run_log.append(payload)
        return payload

    def append_tool_call(self, payload: dict) -> dict:
        self.run_log.append(payload)
        return payload


def _settings(agent_mode: str = "react") -> AgentRequestSettings:
    return AgentRequestSettings(
        user_request="Create a tiny keyboard arcade game.",
        create_type="init",
        agent_mode=agent_mode,
        workspace_capability="read_write",
        workspace_boundary=".worktrees/create-test",
        tool_metadata=build_builtin_tool_registry().list_metadata(),
    )


def run() -> None:
    immediate = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(['{"type":"final","output":{"Finished":true,"message":"done"}}']),
    )
    assert immediate.finished is True
    assert immediate.finish_reason == "finished"
    assert immediate.iterations == 1
    assert immediate.final_output == {"Finished": True, "message": "done"}

    fenced_final = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(['```json\n{"type":"final","output":{"Finished":true,"message":"fenced"}}\n```']),
    )
    assert fenced_final.finished is True
    assert fenced_final.finish_reason == "finished"
    assert fenced_final.final_output == {"Finished": True, "message": "fenced"}

    tool_then_final_adapter = FakeAdapter(
        [
            '{"type":"tool","tool":{"name":"memory.summary_build","args":{"entries":[]}}}',
            '{"type":"final","output":{"Finished":true,"message":"after tool"}}',
        ]
    )
    tool_then_final = run_react_graph(settings=_settings(), model="test-model", adapter=tool_then_final_adapter)
    assert tool_then_final.finished is True
    assert tool_then_final.finish_reason == "finished"
    assert tool_then_final.iterations == 2
    assert len(tool_then_final.tool_results) == 1
    assert tool_then_final.tool_results[0]["ok"] is True
    assert tool_then_final.tool_results[0]["data"]["count"] == 0
    assert len(tool_then_final_adapter.calls) == 2
    assert "toolResults" in tool_then_final_adapter.calls[1]["input"][-1]["content"][0]["text"]

    write_root = Path(__file__).resolve().parents[1] / ".worktrees" / "react-write-test"
    write_then_final = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(
            [
                '{"type":"tool","tool":{"name":"workspace.file_write","args":{"path":"index.html","content":"<html>generated</html>"}}}',
                '{"type":"final","output":{"Finished":true,"files":[{"path":"index.html","workspacePath":"index.html"}],"cover":{"title":"Generated","description":"","tags":[]}}}',
            ]
        ),
        registry=build_builtin_tool_registry(
            WorkspaceContext(
                run_id="react-write-test",
                project_id="project-test",
                workspace_root=str(Path(__file__).resolve().parents[1]),
                worktree_stub_path=str(write_root),
                branch_name=None,
                base_commit=None,
                cleanup_policy="manual",
                isolation_mode="stub",
                capability="read_write",
                status="prepared",
            )
        ),
    )
    assert write_then_final.finished is True
    assert write_then_final.finish_reason == "finished"
    assert write_then_final.tool_results[0]["ok"] is True
    assert (write_root / "index.html").read_text(encoding="utf-8") == "<html>generated</html>"
    assert write_then_final.final_output["files"][0]["workspacePath"] == "index.html"

    metrics = {
        "promptPrefix": "Create request: hello 你好",
        "promptEnglishWords": 3,
        "promptChineseChars": 2,
        "prefixEnglishWords": 3,
        "prefixChineseChars": 2,
        "outputEnglishWords": 2,
        "outputChineseChars": 0,
        "tokenUsage": {"outputTokens": 9},
    }
    spy = MemorySpy()
    recorded = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(['{"type":"final","output":{"Finished":true}}'], metrics=metrics),
        recorder=LLMCallRecorder(long_term_memory=spy, short_term_memory=spy, run_log=spy),
    )
    assert recorded.messages[0]["metrics"]["tokenUsage"]["outputTokens"] == 9
    assert spy.history[0]["metadata"]["kind"] == "llm_call"
    assert spy.llm_calls[0]["metrics"]["promptPrefix"] == "Create request: hello 你好"
    assert spy.run_log[0]["metrics"]["outputEnglishWords"] == 2

    tool_spy = MemorySpy()
    run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(
            [
                '{"type":"tool","tool":{"name":"memory.summary_build","args":{"entries":[]}}}',
                '{"type":"final","output":{"Finished":true}}',
            ]
        ),
        recorder=LLMCallRecorder(short_term_memory=tool_spy, run_log=tool_spy),
    )
    assert any(call.get("kind") == "tool_call" for call in tool_spy.llm_calls)
    assert any(call.get("tool", {}).get("name") == "memory.summary_build" for call in tool_spy.run_log)

    never_done = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(['{"type":"tool","tool":{"name":"memory.summary_build","args":{"entries":[]}}}']),
    )
    assert never_done.finished is True
    assert never_done.finish_reason == "max_iterations"
    assert never_done.iterations == MAX_REACT_ITERATIONS
    assert len(never_done.tool_results) == MAX_REACT_ITERATIONS

    invalid = run_react_graph(settings=_settings(), model="test-model", adapter=FakeAdapter(["not json"]))
    assert invalid.finished is True
    assert invalid.finish_reason == "invalid_react_response"
    assert invalid.final_output
    assert invalid.final_output["Finished"] is True
    assert invalid.final_output["raw"]["error"] == "invalid_json"

    final_without_finished = run_react_graph(
        settings=_settings(),
        model="test-model",
        adapter=FakeAdapter(['{"type":"final","output":{"message":"missing flag"}}']),
    )
    assert final_without_finished.finished is True
    assert final_without_finished.finish_reason == "invalid_react_response"
    assert final_without_finished.final_output
    assert final_without_finished.final_output["Finished"] is True

    strategy = select_agent_strategy(_settings("react"))
    graph_result = strategy.run_langgraph(
        settings=_settings("react"),
        model="test-model",
        adapter=FakeAdapter(['{"type":"final","output":{"Finished":true}}']),
    )
    assert graph_result.strategy == "react"
    assert graph_result.topology == "single-agent"
    assert graph_result.finished is True

    plan_strategy = select_agent_strategy(_settings("plan"))
    plan_graph = plan_strategy.run_langgraph(
        settings=_settings("plan"),
        model="test-model",
        adapter=FakeAdapter(['{"plan":[]}']),
    )
    assert plan_graph.strategy == "plan"
    assert plan_graph.finished is True
    assert plan_graph.finish_reason == "single_step_completed"
    assert plan_graph.iterations == 1

    for strategy_name in list_agent_strategies():
        settings = _settings(strategy_name)
        result = STRATEGY_REGISTRY[strategy_name].run_langgraph(
            settings=settings,
            model="test-model",
            adapter=FakeAdapter(['{"type":"final","output":{"Finished":true}}']),
        )
        assert result.strategy == strategy_name
        assert result.finished is True
        assert result.iterations >= 1


if __name__ == "__main__":
    run()
    print("langgraph react checks passed")
