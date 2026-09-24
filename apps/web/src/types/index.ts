
const TOKEN_STORAGE_KEY = "yahaha_access_token";
export const INIT_AGENT_MODES = ["chat", "react", "plan", "decentralized"] as const;
export const OPT_AGENT_MODES = ["chat", "react", "plan", "decentralized", "refine"] as const;
export const AGENT_MODES = [...INIT_AGENT_MODES, ...OPT_AGENT_MODES] as const;

export type AgentMode = (typeof AGENT_MODES)[number];

export type Game = {
  id: string;
  thumbnailUrl: string | null;
  creatorName: string;
  title: string;
  author: string;
  description: string;
  tags: string[];
  publishedAt: string;
  coverUrl: string;
  plays: number;
  likes: number;
  favorites: number;
  likedByMe: boolean;
  favoritedByMe: boolean;
  section: string;
};

export type GameInteractionState = {
  gameId: string;
  likes: number;
  favorites: number;
  likedByMe: boolean;
  favoritedByMe: boolean;
};

export type GameVersionSummary = {
  versionId: string;
  versionNo: number;
  runtime: string;
  buildStatus: string;
  safetyStatus: string;
  entryFile: string;
  storagePrefix: string;
  manifestUrl: string | null;
  sourceJobId: string | null;
  current: boolean;
  createdAt: string;
};

type RemixResponse = {
  gameId: string;
  gameSlug: string;
  projectId: string | null;
  title: string;
  status: string;
};

type Manifest = {
  id: string;
  title: string;
  runtime: string;
  entry: string;
  bundleUrl: string;
  documentUrl: string | null;
  assets: string[];
};

export type UserProfile = {
  id: string;
  email: string | null;
  displayName: string;
  avatarUrl: string | null;
  role: string;
  lastLoginAt: string | null;
};

export type SessionState = {
  authenticated: boolean;
  user: UserProfile | null;
};

export type AuthResponse = SessionState & {
  token: string;
  accessToken: string | null;
  tokenType: string;
  expiresIn: number | null;
};

type AgentLog = {
  stage: string;
  status: string;
  message: string;
};

export type CreateJob = {
  id: string;
  status: string;
  prompt: string;
  createdAt: string;
  logs: AgentLog[];
  gameId: string | null;
  gameSlug: string | null;
  playUrl: string | null;
  manifestUrl: string | null;
  publishStatus: string | null;
  visibility: string | null;
  versionNo: number | null;
  agentMode: AgentMode | null;
  createType: "init" | "opt" | null;
  projectId: string | null;
  runId: string | null;
  taskId: string | null;
  resumeStatus: string | null;
};

export type CreateProjectPreview = {
  projectId: string;
  gameId: string;
  gameSlug: string;
  title: string;
  description: string | null;
  versionId: string;
  versionNo: number;
  entryFile: string;
  html: string;
  source: Record<string, unknown>;
};

export type CreateInputAsset = {
  assetId: string;
  objectKey: string;
  publicUrl: string | null;
  contentType: string;
  filename: string | null;
  size: number;
};

export type PendingImage = {
  id: string;
  file: File;
  previewUrl: string;
  uploaded?: CreateInputAsset;
};

export type AIConfigState = {
  authenticated: boolean;
  configured: boolean;
  baseUrl?: string | null;
  model?: string | null;
  provider: string | null;
  staticGeneration: boolean;
};

export type LLMTestResult = {
  ok: boolean;
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export type ApiErrorReport = {
  code: string | null;
  message: string;
  llm: LLMTestResult | null;
};

export type RecentGame = {
  gameId: string;
  gameSlug: string;
  title: string;
  playUrl: string;
  jobId: string;
};

export type CreateProject = {
  projectId: string;
  title: string;
  status: string;
  gameId: string | null;
  gameSlug: string | null;
  publishStatus: string | null;
  visibility: string | null;
  currentVersionNo: number | null;
  latestRunId: string | null;
  latestRunStatus: string | null;
  createdAt: string;
  updatedAt: string;
};

export type CreateRunStep = {
  stepNo: number;
  stage: string;
  status: string;
  inputSummary: string | null;
  outputSummary: string | null;
  metrics: Record<string, unknown>;
  createdAt: string;
};

type PlanStep = {
  id: string;
  title: string;
  goal: string;
  toolFamily: string;
  expectedOutput: string;
  acceptanceCheckRefs: string[];
};

type PlanCheck = {
  id: string;
  description: string;
  type: string;
  severity: string;
};

export type PlanPreview = {
  plan: PlanStep[];
  risks: string[];
  acceptanceChecks: PlanCheck[];
  normalizationWarnings?: string[];
};

export type PlanPreviewResponse = {
  runId: string;
  jobId: string | null;
  phase: string | null;
  planPreview: PlanPreview;
};

type DecentralizedCandidatePreview = {
  candidateId: string;
  title: string;
  conceptSummary: string;
  expertRole: string;
  expertDomain: string;
  expertIntro: string;
  styleTags: string[];
  staticHtml: string;
};

export type DecentralizedPreviewResponse = {
  runId: string;
  jobId: string | null;
  phase: string | null;
  selectedCandidateId: string | null;
  candidates: DecentralizedCandidatePreview[];
};

type ProfilePlayRecord = {
  eventId: string;
  eventType: string;
  playedAt: string;
  game: Game;
};

type ProfileProjectIndex = {
  projectId: string;
  title: string;
  status: string;
  gameId: string | null;
  gameSlug: string | null;
  latestRunId: string | null;
  latestRunStatus: string | null;
  updatedAt: string;
};

export type ProfileActivity = {
  recentPlays: ProfilePlayRecord[];
  projects: ProfileProjectIndex[];
};

export type ProfileRunStepRecord = {
  stepNo: number;
  stage: string;
  status: string;
  inputSummary: string | null;
  outputSummary: string | null;
  metrics: Record<string, unknown>;
  createdAt: string;
  recordType: "conversation" | "llm" | "tool" | "lifecycle" | "error";
};

type ProfileProjectRunFeedback = {
  runId: string;
  jobId: string | null;
  status: string;
  createType: string;
  agentMode: string;
  promptSummary: string;
  promptFull: string;
  llmSummary: string;
  llmFull: string;
  createdAt: string;
  completedAt: string | null;
  steps: ProfileRunStepRecord[];
};

export type ProfileProjectDetail = {
  project: ProfileProjectIndex;
  game: Game | null;
  runs: ProfileProjectRunFeedback[];
};

type CreateProjectDeleteResult = {
  projectId: string;
  gameId: string | null;
  gameSlug: string | null;
  deleted: boolean;
  runLogsPreserved: boolean;
};

type MaintenanceJob = {
  id: string;
  status: string;
  currentStage: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  promptSummary: string;
  creatorId: string | null;
  creatorEmail: string | null;
  gameSlug: string | null;
  createdAt: string;
  updatedAt: string;
};

type MaintenanceOverview = {
  jobCounts: Record<string, number>;
  failedJobsLast24h: number;
  pendingReviews: number;
  publicGames: number;
  assetsTotal: number;
  assetsBytes: number;
  recentFailedJobs: MaintenanceJob[];
};

type MaintenanceRunStep = {
  stepNo: number;
  stage: string;
  status: string;
  inputSummary: string | null;
  outputSummary: string | null;
  metrics: Record<string, unknown>;
  outputTokens: number | null;
  createdAt: string;
};

type MaintenanceCreateRun = {
  runId: string;
  jobId: string | null;
  projectId: string;
  projectTitle: string | null;
  createType: string;
  agentMode: string;
  status: string;
  jobStatus: string | null;
  errorCode: string | null;
  errorMessage: string | null;
  promptSummary: string;
  creatorEmail: string | null;
  gameSlug: string | null;
  totalOutputTokens: number;
  startedAt: string;
  completedAt: string | null;
  steps: MaintenanceRunStep[];
};

type MaintenanceGame = {
  id: string;
  slug: string;
  title: string;
  description: string | null;
  visibility: string;
  publishStatus: string;
  plays: number;
  likes: number;
  favorites: number;
  coverAssetId: string | null;
  authorId: string | null;
  updatedAt: string;
};

type MaintenanceAsset = {
  id: string;
  kind: string;
  bucket: string;
  objectKey: string;
  publicUrl: string | null;
  contentType: string | null;
  sizeBytes: number;
  gameId: string | null;
  versionId: string | null;
  jobId: string | null;
  createdAt: string;
};

export type CreateRunEvent = {
  type: "step" | "llm_call" | "tool_call" | "plan_ready" | "decentralized_preview_ready" | "done" | "error" | "heartbeat";
  runId: string;
  stepNo?: number;
  stage?: string;
  status?: string;
  inputSummary?: string | null;
  outputSummary?: string | null;
  metrics?: Record<string, unknown>;
  createdAt?: string;
  summary?: Record<string, unknown>;
};

export const RUN_STAGE_LABELS: Record<string, string> = {
  cover_prompt_rendered: "封面提示词已生成",
  cover_generation_started: "封面智能体开始",
  cover_llm_call: "封面模型返回",
  cover_generated: "封面已生成",
  cover_uploaded: "封面已保存到 MinIO",
  decentralized_preview_generation_started: "去中心化预览开始",
  decentralized_experts_generated: "创意专家已生成",
  decentralized_preview_candidate: "静态候选已生成",
  decentralized_preview_ready: "三选一预览已就绪",
  decentralized_waiting_selection: "等待选择方向",
  decentralized_candidate_selected: "方向已选择",
  decentralized_confirmed: "方向已确认",
  decentralized_final_started: "最终游戏生成开始",
  decentralized_cover_started: "去中心化封面开始",
  decentralized_cover_generated: "去中心化封面已生成"
};

export interface AuthContextValue {
  user: UserProfile | null;
  token: string | null;
  authenticated: boolean;
  expiresIn: number;
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  setTokenAndRefresh: (token: string) => Promise<void>;
}


