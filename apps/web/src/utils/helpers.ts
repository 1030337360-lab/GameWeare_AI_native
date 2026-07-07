// 通用工具函数

import { RUN_STAGE_LABELS, ANONYMOUS_ID_STORAGE_KEY } from "./constants";

export function runStageLabel(stage: string): string {
  return RUN_STAGE_LABELS[stage] ?? stage;
}

export function isPlanPreview(value: unknown): value is { steps: unknown[]; checks: unknown[] } {
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.steps) && Array.isArray(candidate.checks);
}

export function isDecentralizedPreview(value: unknown): value is { candidates: unknown[] } {
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.candidates);
}

export function runRecordTypeLabel(recordType: "llm_call" | "tool_call" | "error" | "done"): string {
  const labels: Record<string, string> = {
    llm_call: "LLM Call",
    tool_call: "Tool Call",
    error: "Error",
    done: "Done",
  };
  return labels[recordType] ?? recordType;
}

export function metricText(metrics: Record<string, unknown>, key: string): string {
  const value = metrics[key];
  if (value === undefined || value === null) return "";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

export function formatStepMetrics(metrics: Record<string, unknown>): string {
  const parts: string[] = [];
  const toolName = metrics.toolName;
  const ok = metrics.ok;
  const files = metrics.files;
  const tokenUsage = metrics.tokenUsage;

  if (typeof toolName === "string") parts.push(`Tool: ${toolName}`);
  if (typeof ok === "boolean") parts.push(ok ? "✓" : "✗");
  if (typeof files === "number") parts.push(`${files} files`);
  if (tokenUsage && typeof tokenUsage === "object") {
    const usage = tokenUsage as Record<string, number>;
    parts.push(`${usage.input ?? 0} → ${usage.output ?? 0} tokens`);
  }

  return parts.join(" | ");
}

export function preparePlayableDocument(html: string): string {
  const storageShim = `<script>
const createMemoryStorage = () => {
  const data = new Map();
  return {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: (key) => data.delete(key),
    clear: () => data.clear(),
    key: (index) => Array.from(data.keys())[index] ?? null,
    get length() { return data.size; },
  };
};
const install = (name) => {
  const original = window[name];
  const memory = createMemoryStorage();
  Object.defineProperty(window, name, {
    get: () => memory,
    set: (value) => { /* ignore */ },
  });
  if (original && original.length > 0) {
    for (let i = 0; i < original.length; i++) {
      const key = original.key(i);
      if (key) memory.setItem(key, original.getItem(key));
    }
  }
};
install("localStorage");
install("sessionStorage");
</script>`;

  const sanitized = html
    .replace(/<script\b[^>]*>([\s\S]*?)<\/script>/gi, "")
    .replace(/javascript:/gi, "")
    .replace(/on\w+\s*=/gi, "");

  return storageShim + sanitized;
}

export function getAnonymousId(): string {
  const existing = localStorage.getItem(ANONYMOUS_ID_STORAGE_KEY);
  if (existing) return existing;
  const nextId = crypto.randomUUID();
  localStorage.setItem(ANONYMOUS_ID_STORAGE_KEY, nextId);
  return nextId;
}

export function buildGameQuery(search: string, tag: string): string {
  const params = new URLSearchParams();
  if (search) params.set("q", search);
  if (tag) params.set("tag", tag);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function formatPlays(plays: number): string {
  if (plays >= 1000000) return `${(plays / 1000000).toFixed(1)}M`;
  if (plays >= 1000) return `${(plays / 1000).toFixed(1)}K`;
  return String(plays);
}

export function formatBytes(value: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let unitIndex = 0;
  let size = value;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex++;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
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
  const detail = typeof root.detail === "string" ? root.detail : (typeof root.detail === "object" && root.detail !== null ? (root.detail as Record<string, unknown>) : "");

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
