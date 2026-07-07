// 全局常量

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
export const TOKEN_STORAGE_KEY = "yahaha_auth_token";
export const ANONYMOUS_ID_STORAGE_KEY = "yahaha_anonymous_id";

export const INIT_AGENT_MODES = ["chat", "react", "plan", "decentralized"] as const;
export const OPT_AGENT_MODES = ["chat", "react", "plan", "decentralized", "refine"] as const;
export const AGENT_MODES = [...INIT_AGENT_MODES, ...OPT_AGENT_MODES] as const;

export const RUN_STAGE_LABELS: Record<string, string> = {
  plan: "Plan",
  code: "Code",
  test: "Test",
  review: "Review",
  deploy: "Deploy",
};
