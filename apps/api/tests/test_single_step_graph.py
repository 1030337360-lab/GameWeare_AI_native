from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.framework.workspace import WorkspaceContext
from app.agents.graphs.errors import LLMProviderCallError
from app.agents.graphs.llm_adapter import LLMGraphResult
from app.agents.graphs.recording import LLMCallRecorder
from app.agents.graphs.single_step_graph import MAX_SINGLE_STEP_ITERATIONS
from app.agents.strategies import AgentRequestSettings, select_agent_strategy
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


class ProviderErrorAdapter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke(self, payload: dict) -> LLMGraphResult:
        self.calls.append(payload)
        raw = {"ok": False, "statusCode": 502, "error": {"code": "bad_gateway", "message": "upstream failed"}}
        return LLMGraphResult(text="", raw=raw, metrics={"promptPrefix": "failed", "tokenUsage": {"outputTokens": None}})


class MemorySpy:
    def __init__(self) -> None:
        self.llm_calls: list[dict] = []
        self.run_log: list[dict] = []
        self.file_edits: list[dict] = []

    def record_llm_call(self, payload: dict) -> None:
        self.llm_calls.append(payload)

    def append_llm_call(self, payload: dict) -> dict:
        self.run_log.append(payload)
        return payload

    def append_tool_call(self, payload: dict) -> dict:
        self.run_log.append(payload)
        return payload

    def record_file_edit(self, payload: dict) -> None:
        self.file_edits.append(payload)


def _settings(agent_mode: str = "chat") -> AgentRequestSettings:
    registry = build_builtin_tool_registry()
    return AgentRequestSettings(
        user_request="Create a tiny game.",
        create_type="init",
        agent_mode=agent_mode,
        workspace_capability="read_write",
        workspace_boundary=".worktrees/single-step-test",
        tool_metadata=registry.list_metadata(),
    )


def _workspace_registry(name: str):
    api_root = Path(__file__).resolve().parents[1]
    write_root = api_root / ".worktrees" / name
    if write_root.exists():
        shutil.rmtree(write_root)
    write_root.mkdir(parents=True, exist_ok=True)
    return build_builtin_tool_registry(
        WorkspaceContext(
            run_id=name,
            project_id="project-test",
            workspace_root=str(api_root),
            worktree_stub_path=str(write_root),
            branch_name=None,
            base_commit=None,
            cleanup_policy="manual",
            isolation_mode="stub",
            capability="read_write",
            status="prepared",
        )
    ), write_root


def run() -> None:
    strategy = select_agent_strategy(_settings("chat"))
    direct = strategy.run_langgraph(
        settings=_settings("chat"),
        model="test-model",
        adapter=FakeAdapter(['{"type":"final","output":{"Finished":true,"message":"done"}}']),
    )
    assert direct.finished is True
    assert direct.finish_reason == "finished"
    assert direct.iterations == 1
    assert direct.final_output == {"Finished": True, "message": "done"}

    legacy = strategy.run_langgraph(
        settings=_settings("chat"),
        model="test-model",
        adapter=FakeAdapter(['{"files":[]}']),
    )
    assert legacy.finished is True
    assert legacy.finish_reason == "single_step_completed"
    assert legacy.final_output and legacy.final_output["text"] == '{"files":[]}'

    registry, write_root = _workspace_registry("single-step-write-test")
    try:
        spy = MemorySpy()
        large_html = "<html>" + ("x" * 5000) + "</html>"
        write_then_final_adapter = FakeAdapter(
            [
                '{"type":"tool","tool":{"name":"workspace.file_write","args":{"path":"index.html","content":"'
                + large_html
                + '"}}}',
                '{"type":"final","output":{"Finished":true,"files":[{"path":"index.html","workspacePath":"index.html"}],"cover":{"title":"Tool Game","description":"","tags":[]},"implementationSummary":"Wrote through tool.","safetyNotes":["No privileged APIs."]}}',
            ]
        )
        result = strategy.run_langgraph(
            settings=_settings("chat"),
            model="test-model",
            adapter=write_then_final_adapter,
            registry=registry,
            recorder=LLMCallRecorder(short_term_memory=spy, run_log=spy),
        )
        assert result.finished is True
        assert result.finish_reason == "finished"
        assert result.iterations == 2
        assert result.tool_results[0]["ok"] is True
        assert (write_root / "index.html").read_text(encoding="utf-8") == large_html
        assert result.final_output and result.final_output["files"][0]["workspacePath"] == "index.html"
        continuation_text = write_then_final_adapter.calls[1]["input"][-1]["content"][0]["text"]
        assert "toolResults" in continuation_text
        assert "contentChars" in continuation_text
        assert "x" * 2000 not in continuation_text
        assert any(call.get("kind") == "tool_call" for call in spy.llm_calls)
        assert any(call.get("tool", {}).get("name") == "workspace.file_write" for call in spy.run_log)
        assert spy.file_edits and spy.file_edits[0]["path"] == "index.html"
    finally:
        shutil.rmtree(write_root, ignore_errors=True)

    never_done = strategy.run_langgraph(
        settings=_settings("chat"),
        model="test-model",
        adapter=FakeAdapter(['{"type":"tool","tool":{"name":"memory.summary_build","args":{"entries":[]}}}']),
    )
    assert never_done.finished is True
    assert never_done.finish_reason == "max_iterations"
    assert never_done.iterations == MAX_SINGLE_STEP_ITERATIONS
    assert len(never_done.tool_results) == MAX_SINGLE_STEP_ITERATIONS

    try:
        strategy.run_langgraph(settings=_settings("chat"), model="test-model", adapter=ProviderErrorAdapter())
    except LLMProviderCallError as exc:
        assert exc.diagnostics["statusCode"] == 502
        assert exc.diagnostics["code"] == "bad_gateway"
    else:
        raise AssertionError("single-step provider errors must be surfaced")


if __name__ == "__main__":
    run()
    print("single-step graph checks passed")
