from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import get_settings


@dataclass(frozen=True)
class LLMGraphResult:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


class LLMGraphAdapter(Protocol):
    def invoke(self, payload: dict[str, Any]) -> LLMGraphResult:
        ...


def _responses_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/responses"):
        return normalized
    return f"{normalized}/responses"


def _iter_input_text(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in payload.get("input", []):
        if isinstance(item, str):
            texts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            texts.append(content)
            continue
        if isinstance(content, list):
            for content_item in content:
                if isinstance(content_item, str):
                    texts.append(content_item)
                elif isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                    texts.append(content_item["text"])
    return texts


def _language_counts(text: str) -> dict[str, int]:
    english_words = re.findall(r"[A-Za-z]+(?:['-][A-Za-z]+)?", text)
    chinese_chars = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text)
    return {
        "englishWords": len(english_words),
        "chineseChars": len(chinese_chars),
    }


def _token_usage(raw: dict[str, Any]) -> dict[str, int | None]:
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    output_tokens = (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("completionTokens")
    )
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("promptTokens")
    total_tokens = usage.get("total_tokens") or usage.get("totalTokens")
    return {
        "inputTokens": input_tokens if isinstance(input_tokens, int) else None,
        "outputTokens": output_tokens if isinstance(output_tokens, int) else None,
        "totalTokens": total_tokens if isinstance(total_tokens, int) else None,
    }


def build_llm_call_metrics(
    request_payload: dict[str, Any],
    *,
    response_text: str,
    response_raw: dict[str, Any] | None = None,
    prefix_char_limit: int = 600,
) -> dict[str, Any]:
    prompt_text = "\n".join(_iter_input_text(request_payload))
    prefix = prompt_text[:prefix_char_limit]
    prompt_counts = _language_counts(prompt_text)
    prefix_counts = _language_counts(prefix)
    output_counts = _language_counts(response_text)
    return {
        "model": request_payload.get("model"),
        "promptPrefix": prefix,
        "promptPrefixCharLimit": prefix_char_limit,
        "promptTextChars": len(prompt_text),
        "promptPrefixChars": len(prefix),
        "promptEnglishWords": prompt_counts["englishWords"],
        "promptChineseChars": prompt_counts["chineseChars"],
        "prefixEnglishWords": prefix_counts["englishWords"],
        "prefixChineseChars": prefix_counts["chineseChars"],
        "outputTextChars": len(response_text),
        "outputEnglishWords": output_counts["englishWords"],
        "outputChineseChars": output_counts["chineseChars"],
        "tokenUsage": _token_usage(response_raw or {}),
    }


def _redact(value: str, secret: str) -> str:
    redacted = value.replace(secret, "[redacted]") if secret else value
    return re.sub(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b", "[redacted]", redacted)


def extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text
    output = payload.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if isinstance(content_item, dict):
                        text = content_item.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
        if chunks:
            return "\n".join(chunks)
    return json.dumps(payload, ensure_ascii=False)


class OpenAIResponsesGraphAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else get_settings().llm_request_timeout_seconds
        self.transport = transport

    def invoke(self, payload: dict[str, Any]) -> LLMGraphResult:
        endpoint = _responses_url(self.base_url)
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True, transport=self.transport) as client:
                response = client.post(
                    endpoint,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            response_payload = response.json()
        except httpx.RequestError as exc:
            response_raw = {
                "ok": False,
                "error": {
                    "code": "llm_request_error",
                    "message": _redact(str(exc), self.api_key)[:500],
                },
            }
            return LLMGraphResult(
                text="",
                raw=response_raw,
                metrics=build_llm_call_metrics(payload, response_text="", response_raw=response_raw),
            )
        except ValueError:
            response_raw = {"ok": False, "error": {"code": "llm_invalid_json_response"}}
            return LLMGraphResult(
                text="",
                raw=response_raw,
                metrics=build_llm_call_metrics(payload, response_text="", response_raw=response_raw),
            )

        if response.status_code >= 400:
            response_raw = {
                "ok": False,
                "statusCode": response.status_code,
                "error": response_payload if isinstance(response_payload, dict) else {},
            }
            return LLMGraphResult(
                text="",
                raw=response_raw,
                metrics=build_llm_call_metrics(payload, response_text="", response_raw=response_raw),
            )
        if not isinstance(response_payload, dict):
            response_raw = {"ok": False, "error": {"code": "llm_invalid_response"}}
            return LLMGraphResult(
                text="",
                raw=response_raw,
                metrics=build_llm_call_metrics(payload, response_text="", response_raw=response_raw),
            )
        response_text = extract_responses_text(response_payload)
        return LLMGraphResult(
            text=response_text,
            raw=response_payload,
            metrics=build_llm_call_metrics(payload, response_text=response_text, response_raw=response_payload),
        )
