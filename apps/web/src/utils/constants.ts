// 全局常量

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
export const TOKEN_STORAGE_KEY = "gameweare_auth_token";
export const ANONYMOUS_ID_STORAGE_KEY = "gameweare_anonymous_id";

export const INIT_AGENT_MODES = ["chat", "react", "plan", "decentralized"] as const;
export const OPT_AGENT_MODES = ["chat", "react", "plan", "decentralized", "refine"] as const;
export const AGENT_MODES = [...INIT_AGENT_MODES, ...OPT_AGENT_MODES] as const;

export const RUN_STAGE_LABELS: Record<string, string> = {
  plan: "规划", code: "编写游戏", test: "编译验证", review: "成果审查", deploy: "发布",
  queued: "等待执行", planning: "规划中", generating: "生成中", llm_call: "模型生成",
  cover_llm_call: "生成封面", cover_generation_started: "开始生成封面", cover_reused: "沿用原封面", cover_uploaded: "封面已保存", generation: "生成游戏", compile: "编译验证",
  validate: "校验", validation: "校验", completed: "已完成", failed: "失败",
};
