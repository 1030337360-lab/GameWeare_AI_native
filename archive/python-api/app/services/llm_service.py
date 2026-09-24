from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.agents.prompts import render_connection_test_payload
from app.schemas import LLMTestResult

OPENAI_WIRE_API = "responses"


def _redact_sensitive_text(value: str, secret: str | None = None) -> str:
    redacted = value
    if secret:
        redacted = redacted.replace(secret, "[redacted]")
    return re.sub(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b", "[redacted]", redacted)


def _safe_provider_message(payload: Any, secret: str | None = None) -> str | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return _redact_sensitive_text(message, secret)[:500]
    message = payload.get("message")
    if isinstance(message, str):
        return _redact_sensitive_text(message, secret)[:500]
    return None


def _responses_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("baseUrl must be an absolute http(s) URL")
    if normalized.endswith("/responses"):
        return normalized
    return f"{normalized}/responses"


def _has_responses_output(payload: dict[str, Any]) -> bool:
    output = payload.get("output")
    if isinstance(output, list) and output:
        return True
    output_text = payload.get("output_text")
    return isinstance(output_text, str) and bool(output_text.strip())


def _http_error_result(status_code: int, payload: Any, api_key: str) -> LLMTestResult:
    provider_message = _safe_provider_message(payload, api_key)
    details = {"statusCode": status_code}
    if provider_message:
        details["providerMessage"] = provider_message

    if status_code in (401, 403):
        return LLMTestResult(
            ok=False,
            code="invalid_api_key",
            message="The API key was rejected by the LLM provider.",
            details=details,
        )
    if status_code == 404:
        return LLMTestResult(
            ok=False,
            code="endpoint_or_model_not_found",
            message="The LLM endpoint or model was not found. Check base_url and model.",
            details=details,
        )
    if status_code == 429:
        return LLMTestResult(
            ok=False,
            code="rate_limited",
            message="The LLM provider rate limit was reached.",
            details=details,
        )
    if status_code >= 500:
        return LLMTestResult(
            ok=False,
            code="provider_error",
            message="The LLM provider returned a server error.",
            details=details,
        )
    return LLMTestResult(
        ok=False,
        code="request_rejected",
        message="The LLM provider rejected the test request. Check base_url, model, and api_key.",
        details=details,
    )


def test_llm_config(
    base_url: str,
    model: str,
    api_key: str,
    *,
    timeout_seconds: float | None = None,
    transport: httpx.BaseTransport | None = None,
) -> LLMTestResult:
    try:
        endpoint = _responses_url(base_url)
    except ValueError as exc:
        return LLMTestResult(
            ok=False,
            code="invalid_base_url",
            message=str(exc),
            details={},
        )

    cleaned_model = model.strip()
    cleaned_api_key = api_key.strip()
    if not cleaned_model:
        return LLMTestResult(ok=False, code="missing_model", message="model is required.", details={})
    if not cleaned_api_key:
        return LLMTestResult(ok=False, code="missing_api_key", message="api_key is required.", details={})

    request_payload = render_connection_test_payload(cleaned_model)
    timeout = timeout_seconds if timeout_seconds is not None else get_settings().llm_request_timeout_seconds

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport) as client:
            response = client.post(
                endpoint,
                json=request_payload,
                headers={
                    "Authorization": f"Bearer {cleaned_api_key}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.TimeoutException:
        return LLMTestResult(
            ok=False,
            code="timeout",
            message="The LLM provider did not respond before the timeout.",
            details={"endpoint": endpoint, "wireApi": OPENAI_WIRE_API, "timeoutSeconds": timeout},
        )
    except httpx.ConnectError:
        return LLMTestResult(
            ok=False,
            code="connection_error",
            message="Could not connect to the LLM base_url. Check the address and network.",
            details={"endpoint": endpoint, "wireApi": OPENAI_WIRE_API},
        )
    except httpx.RequestError as exc:
        return LLMTestResult(
            ok=False,
            code="request_error",
            message="The LLM test request could not be completed.",
            details={
                "endpoint": endpoint,
                "wireApi": OPENAI_WIRE_API,
                "error": _redact_sensitive_text(str(exc), cleaned_api_key)[:500],
            },
        )

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if response.status_code >= 400:
        return _http_error_result(response.status_code, payload, cleaned_api_key)
    if not isinstance(payload, dict):
        return LLMTestResult(
            ok=False,
            code="invalid_response",
            message="The LLM provider returned a non-JSON response.",
            details={"statusCode": response.status_code},
        )

    if not _has_responses_output(payload):
        return LLMTestResult(
            ok=False,
            code="invalid_response",
            message="The LLM provider response did not include Responses API output.",
            details={"statusCode": response.status_code},
        )

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return LLMTestResult(
        ok=True,
        code="ok",
        message="LLM configuration test passed.",
        details={
            "statusCode": response.status_code,
            "model": payload.get("model") or cleaned_model,
            "wireApi": OPENAI_WIRE_API,
            "usage": usage,
        },
    )
