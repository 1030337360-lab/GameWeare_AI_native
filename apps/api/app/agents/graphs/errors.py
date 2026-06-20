from __future__ import annotations

from typing import Any


class LLMProviderCallError(RuntimeError):
    def __init__(self, diagnostics: dict[str, Any]):
        self.diagnostics = diagnostics
        code = str(diagnostics.get("code") or "llm_provider_error")
        message = str(diagnostics.get("message") or "The LLM provider call failed.")
        super().__init__(f"{code}: {message}")


def provider_error_diagnostics(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("ok") is not False:
        return None
    error = raw.get("error") if isinstance(raw.get("error"), dict) else {}
    provider_error = error.get("error") if isinstance(error.get("error"), dict) else {}
    message = (
        error.get("message")
        or provider_error.get("message")
        or raw.get("message")
        or "The LLM provider call failed."
    )
    code = (
        error.get("code")
        or provider_error.get("code")
        or raw.get("code")
        or "llm_provider_error"
    )
    diagnostics: dict[str, Any] = {
        "ok": False,
        "code": str(code)[:120],
        "message": str(message)[:800],
    }
    status_code = raw.get("statusCode") or raw.get("status_code")
    if isinstance(status_code, int):
        diagnostics["statusCode"] = status_code
    attempt = raw.get("attempt")
    attempts = raw.get("attempts")
    if isinstance(attempt, int):
        diagnostics["attempt"] = attempt
    if isinstance(attempts, int):
        diagnostics["attempts"] = attempts
    provider_type = provider_error.get("type") or error.get("type")
    if isinstance(provider_type, str):
        diagnostics["providerType"] = provider_type[:120]
    request_id = raw.get("requestId") or raw.get("request_id")
    if isinstance(request_id, str):
        diagnostics["requestId"] = request_id[:160]
    return diagnostics


def ensure_provider_success(raw: dict[str, Any] | None) -> None:
    diagnostics = provider_error_diagnostics(raw)
    if diagnostics:
        raise LLMProviderCallError(diagnostics)
