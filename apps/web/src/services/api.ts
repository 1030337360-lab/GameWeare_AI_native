// API 基础请求封装

import { API_BASE_URL } from "../utils/constants";
import type { ApiErrorReport } from "../types";

export async function fetchJson<T>(
  path: string,
  fallback: T,
  token?: string | null
): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
    if (!response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

export async function readApiError(response: Response): Promise<{ status: number; message: string; detail: string | Record<string, unknown> }> {
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      return { status: response.status, message: text, detail: "" };
    }
  }

  const root =
    payload && typeof payload === "object"
      ? (payload as Record<string, unknown>)
      : ({} as Record<string, unknown>);
  const detail: string | Record<string, unknown> = typeof root.detail === "string" ? root.detail : (typeof root.detail === "object" && root.detail !== null ? (root.detail as Record<string, unknown>) : "");

  let message = "";
  if (typeof detail === "string") {
    message = detail;
  } else if (detail && typeof detail === "object") {
    const data = detail as Record<string, unknown>;
    const llm =
      data.llm && typeof data.llm === "object"
        ? (data.llm as Record<string, unknown>)
        : null;
    const providerMessage =
      llm && typeof llm.message === "string" ? llm.message : "";
    const message_ =
      typeof data.message === "string"
        ? data.message
        : typeof data.error === "string"
        ? data.error
        : "";
    message = providerMessage || message_ || JSON.stringify(detail);
  }

  return { status: response.status, message, detail };
}

export function buildApiFetch(token: string | null) {
  return (path: string, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  };
}
