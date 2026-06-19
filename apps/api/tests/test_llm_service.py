from pathlib import Path
import json
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.graphs.llm_adapter import OpenAIResponsesGraphAdapter, build_llm_call_metrics
from app.services.llm_service import test_llm_config


def _transport(status_code: int, payload: dict | str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        assert request.headers["authorization"] == "Bearer test-key"
        request_payload = json.loads(request.content)
        assert request_payload["model"] == "test-model"
        assert isinstance(request_payload["input"], list)
        assert request_payload["reasoning"]["effort"] == "medium"
        assert request_payload["max_output_tokens"] <= 64
        if isinstance(payload, str):
            return httpx.Response(status_code, text=payload)
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


def run() -> None:
    success = test_llm_config(
        "https://api.example.test/v1",
        "test-model",
        "test-key",
        transport=_transport(
            200,
            {
                "id": "resp-test",
                "model": "test-model",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
                "usage": {"total_tokens": 3},
            },
        ),
    )
    assert success.ok is True
    assert success.code == "ok"
    assert success.details["usage"]["total_tokens"] == 3

    invalid_key = test_llm_config(
        "https://api.example.test/v1",
        "test-model",
        "test-key",
        transport=_transport(401, {"error": {"message": "Incorrect API key provided."}}),
    )
    assert invalid_key.ok is False
    assert invalid_key.code == "invalid_api_key"
    assert invalid_key.details["statusCode"] == 401
    assert "providerMessage" in invalid_key.details

    missing_model = test_llm_config(
        "https://api.example.test/v1",
        "test-model",
        "test-key",
        transport=_transport(404, {"error": {"message": "Model does not exist."}}),
    )
    assert missing_model.ok is False
    assert missing_model.code == "endpoint_or_model_not_found"

    def connection_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed", request=request)

    bad_base_url = test_llm_config(
        "https://missing.example.test/v1",
        "test-model",
        "test-key",
        transport=httpx.MockTransport(connection_error),
    )
    assert bad_base_url.ok is False
    assert bad_base_url.code == "connection_error"

    def timeout_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    timeout = test_llm_config(
        "https://api.example.test/v1",
        "test-model",
        "test-key",
        timeout_seconds=33,
        transport=httpx.MockTransport(timeout_error),
    )
    assert timeout.ok is False
    assert timeout.code == "timeout"
    assert timeout.details["timeoutSeconds"] == 33

    invalid_url = test_llm_config("not-a-url", "test-model", "test-key")
    assert invalid_url.ok is False
    assert invalid_url.code == "invalid_base_url"

    malformed = test_llm_config(
        "https://api.example.test/v1",
        "test-model",
        "test-key",
        transport=_transport(200, {"id": "resp-test", "output": []}),
    )
    assert malformed.ok is False
    assert malformed.code == "invalid_response"

    metrics = build_llm_call_metrics(
        {
            "model": "test-model",
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": "You are pragmatic."}]},
                {"role": "user", "content": [{"type": "input_text", "text": "制作 game with coins"}]},
            ],
        },
        response_text="Finished game",
        response_raw={"usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}},
    )
    assert metrics["promptPrefix"].startswith("You are pragmatic.")
    assert metrics["promptEnglishWords"] >= 5
    assert metrics["promptChineseChars"] == 2
    assert metrics["outputEnglishWords"] == 2
    assert metrics["tokenUsage"]["outputTokens"] == 7

    graph_adapter = OpenAIResponsesGraphAdapter(
        base_url="https://api.example.test/v1",
        api_key="test-key",
        transport=_transport(
            200,
            {
                "id": "resp-test",
                "model": "test-model",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Finished"}],
                    }
                ],
                "usage": {"output_tokens": 5, "total_tokens": 13},
            },
        ),
    )
    graph_result = graph_adapter.invoke(
        {
            "model": "test-model",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hello 世界"}]}],
            "reasoning": {"effort": "medium"},
            "max_output_tokens": 16,
        }
    )
    assert graph_result.text == "Finished"
    assert graph_result.metrics["prefixEnglishWords"] == 1
    assert graph_result.metrics["prefixChineseChars"] == 2
    assert graph_result.metrics["tokenUsage"]["outputTokens"] == 5


if __name__ == "__main__":
    run()
    print("llm service checks passed")
