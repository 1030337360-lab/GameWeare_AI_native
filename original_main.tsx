import React from "react";
import { createRoot } from "react-dom/client";
import {
  BrowserRouter,
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams
} from "react-router-dom";
import { Bookmark, Eye, EyeOff, Gamepad2, Heart, Home as HomeIcon, LogOut, Play, Plus, Search, Settings, Sparkles, UserRound } from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
const TOKEN_STORAGE_KEY = "yahaha_access_token";
const INIT_AGENT_MODES = ["chat", "react", "plan", "decentralized"] as const;
const OPT_AGENT_MODES = ["chat", "react", "plan", "decentralized", "refine"] as const;
const AGENT_MODES = [...INIT_AGENT_MODES, ...OPT_AGENT_MODES] as const;

type AgentMode = (typeof AGENT_MODES)[number];

type Game = {
  id: string;
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

type GameInteractionState = {
  gameId: string;
  likes: number;
  favorites: number;
  likedByMe: boolean;
  favoritedByMe: boolean;
};

type GameVersionSummary = {
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

type UserProfile = {
  id: string;
  email: string | null;
  displayName: string;
  avatarUrl: string | null;
  role: string;
  lastLoginAt: string | null;
};

type SessionState = {
  authenticated: boolean;
  user: UserProfile | null;
};

type AuthResponse = SessionState & {
  accessToken: string | null;
  tokenType: string;
  expiresIn: number | null;
};

type AgentLog = {
  stage: string;
  status: string;
  message: string;
};

type CreateJob = {
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

type CreateProjectPreview = {
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

type CreateInputAsset = {
  assetId: string;
  objectKey: string;
  publicUrl: string | null;
  contentType: string;
  filename: string | null;
  size: number;
};

type PendingImage = {
  id: string;
  file: File;
  previewUrl: string;
  uploaded?: CreateInputAsset;
};

type AIConfigState = {
  authenticated: boolean;
  configured: boolean;
  baseUrl?: string | null;
  model?: string | null;
  provider: string | null;
  staticGeneration: boolean;
};

type LLMTestResult = {
  ok: boolean;
  code: string;
  message: string;
  details: Record<string, unknown>;
};

type ApiErrorReport = {
  code: string | null;
  message: string;
  llm: LLMTestResult | null;
};

type RecentGame = {
  gameId: string;
  gameSlug: string;
  title: string;
  playUrl: string;
  jobId: string;
};

type CreateProject = {
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

type CreateRunStep = {
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

type PlanPreview = {
  plan: PlanStep[];
  risks: string[];
  acceptanceChecks: PlanCheck[];
  normalizationWarnings?: string[];
};

type PlanPreviewResponse = {
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

type DecentralizedPreviewResponse = {
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

type ProfileActivity = {
  recentPlays: ProfilePlayRecord[];
  projects: ProfileProjectIndex[];
};

type ProfileRunStepRecord = {
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

type ProfileProjectDetail = {
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

type CreateRunEvent = {
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

const RUN_STAGE_LABELS: Record<string, string> = {
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

function runStageLabel(stage: string) {
  return RUN_STAGE_LABELS[stage] ?? stage;
}

function isPlanPreview(value: unknown): value is PlanPreview {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.plan) && Array.isArray(candidate.risks) && Array.isArray(candidate.acceptanceChecks);
}

function isDecentralizedPreview(value: unknown): value is DecentralizedPreviewResponse {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return Array.isArray(candidate.candidates);
}

function runRecordTypeLabel(recordType: ProfileRunStepRecord["recordType"]) {
  const labels: Record<ProfileRunStepRecord["recordType"], string> = {
    conversation: "Conversation",
    llm: "LLM",
    tool: "Tool",
    lifecycle: "Lifecycle",
    error: "Error"
  };
  return labels[recordType];
}

function metricText(metrics: Record<string, unknown>, key: string) {
  const value = metrics[key];
  if (value === null || value === undefined || value === "") return "-";
  if (Array.isArray(value)) return value.join(", ") || "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatStepMetrics(metrics: Record<string, unknown>) {
  const parts: string[] = [];
  const toolName = metrics.toolName;
  const ok = metrics.ok;
  const files = metrics.files;
  const tokenUsage = metrics.tokenUsage;
  if (toolName) parts.push(`tool ${String(toolName)}`);
  if (ok !== undefined) parts.push(`ok ${String(ok)}`);
  if (Array.isArray(files) && files.length) parts.push(`files ${files.slice(0, 3).join(", ")}`);
  if (tokenUsage && typeof tokenUsage === "object") parts.push(`usage ${JSON.stringify(tokenUsage)}`);
  return parts.join(" · ") || "No extra metrics";
}

function preparePlayableDocument(html: string) {
  const storageShim = `<script>
(() => {
  const createMemoryStorage = () => {
    const data = new Map();
    return {
      get length() { return data.size; },
      key(index) { return Array.from(data.keys())[Number(index)] ?? null; },
      getItem(key) { key = String(key); return data.has(key) ? data.get(key) : null; },
      setItem(key, value) { data.set(String(key), String(value)); },
      removeItem(key) { data.delete(String(key)); },
      clear() { data.clear(); }
    };
  };
  window.__yahahaMemoryLocalStorage = window.__yahahaMemoryLocalStorage || createMemoryStorage();
  window.__yahahaMemorySessionStorage = window.__yahahaMemorySessionStorage || createMemoryStorage();
  const install = (name) => {
    try { void window[name]; return; } catch {}
    try {
      Object.defineProperty(window, name, {
        value: name === "localStorage" ? window.__yahahaMemoryLocalStorage : window.__yahahaMemorySessionStorage,
        configurable: true
      });
    } catch {}
  };
  install("localStorage");
  install("sessionStorage");
})();
</script>`;
  const sanitized = html
    .replace(/cursor\s*:\s*[^;}"']+;?/gi, "")
    .replace(/if\s*\([^)]*requestPointerLock[^)]*\)\s*[^;{}]*requestPointerLock\([^)]*\);?/gi, "")
    .replace(/[^;\n{}]*requestPointerLock\([^)]*\);?/gi, "")
    .replace(/\b(?:window|globalThis|self)\s*\.\s*localStorage\b/g, "window.__yahahaMemoryLocalStorage")
    .replace(/\b(?:window|globalThis|self)\s*\.\s*sessionStorage\b/g, "window.__yahahaMemorySessionStorage")
    .replace(/(^|[^.\w$])localStorage\b/g, "$1window.__yahahaMemoryLocalStorage")
    .replace(/(^|[^.\w$])sessionStorage\b/g, "$1window.__yahahaMemorySessionStorage");
  if (/<head[^>]*>/i.test(sanitized)) {
    return sanitized.replace(/<head([^>]*)>/i, `<head$1>${storageShim}`);
  }
  return storageShim + sanitized;
}

const ANONYMOUS_ID_STORAGE_KEY = "yahaha_anonymous_id";

function getAnonymousId() {
  const existing = localStorage.getItem(ANONYMOUS_ID_STORAGE_KEY);
  if (existing) return existing;
  const nextId = crypto.randomUUID();
  localStorage.setItem(ANONYMOUS_ID_STORAGE_KEY, nextId);
  return nextId;
}

function buildGameQuery(search: string, tag: string) {
  const params = new URLSearchParams();
  if (search.trim()) params.set("q", search.trim());
  if (tag.trim()) params.set("tag", tag.trim());
  const query = params.toString();
  return query ? `/games?${query}` : "/games";
}

type AuthContextValue = SessionState & {
  loading: boolean;
  token: string | null;
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  setTokenAndRefresh: (token: string) => Promise<void>;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

const fallbackGames: Game[] = [
  {
    id: "astro-ludo",
    title: "Astro Ludo",
    author: "xiaoling",
    description: "Fast tabletop moves in a glowing space arcade.",
    tags: ["Board", "Arcade"],
    publishedAt: "2026-06-18T10:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1614728894747-a83421e2b9c9?auto=format&fit=crop&w=900&q=80",
    plays: 1200000,
    likes: 42000,
    favorites: 18000,
    likedByMe: false,
    favoritedByMe: false,
    section: "Players' Choice"
  },
  {
    id: "color-bloom",
    title: "Color Bloom",
    author: "emanfatima",
    description: "A bright matching puzzle generated from a single prompt.",
    tags: ["Puzzle", "Generated"],
    publishedAt: "2026-06-18T11:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=900&q=80",
    plays: 700000,
    likes: 26000,
    favorites: 9400,
    likedByMe: false,
    favoritedByMe: false,
    section: "Trending"
  },
  {
    id: "rail-in-air",
    title: "Rail in Air",
    author: "Majisok",
    description: "Balance a flying rail cart through neon gates.",
    tags: ["Runner", "Physics"],
    publishedAt: "2026-06-18T12:00:00Z",
    coverUrl: "https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=80",
    plays: 4500000,
    likes: 87000,
    favorites: 33000,
    likedByMe: false,
    favoritedByMe: false,
    section: "Recommended For You"
  }
];

async function fetchJson<T>(path: string, fallback: T, token?: string | null): Promise<T> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    });
    if (!response.ok) return fallback;
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

async function readApiError(response: Response): Promise<ApiErrorReport> {
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      return { code: null, message: text, llm: null };
    }
  }
  const root = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  const detail = root.detail ?? root;
  if (typeof detail === "string") {
    return { code: null, message: detail, llm: null };
  }
  if (!detail || typeof detail !== "object") {
    return { code: null, message: response.statusText || "Request failed.", llm: null };
  }
  const data = detail as Record<string, unknown>;
  const llm = data.llm && typeof data.llm === "object" ? data.llm as LLMTestResult : null;
  const providerMessage =
    llm?.details?.providerMessage && typeof llm.details.providerMessage === "string"
      ? ` Provider message: ${llm.details.providerMessage}`
      : "";
  const message =
    (llm ? `${llm.message}${providerMessage}` : null) ||
    (typeof data.message === "string" ? data.message : null) ||
    (typeof data.code === "string" ? data.code : null) ||
    response.statusText ||
    "Request failed.";
  return {
    code: typeof data.code === "string" ? data.code : null,
    message,
    llm
  };
}

function useAuth() {
  const context = React.useContext(AuthContext);
  if (!context) throw new Error("Auth context is missing");
  return context;
}

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(() => localStorage.getItem(TOKEN_STORAGE_KEY));
  const [session, setSession] = React.useState<SessionState>({ authenticated: false, user: null });
  const [loading, setLoading] = React.useState(() => Boolean(localStorage.getItem(TOKEN_STORAGE_KEY)));

  const apiFetch = React.useCallback(
    (path: string, init: RequestInit = {}) => {
      const headers = new Headers(init.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    },
    [token]
  );

  const loadSession = React.useCallback(async (nextToken = token) => {
    setLoading(true);
    if (!nextToken) {
      setSession({ authenticated: false, user: null });
      setLoading(false);
      return;
    }
    try {
      const response = await fetch(`${API_BASE_URL}/auth/session`, {
        headers: { Authorization: `Bearer ${nextToken}` }
      });
      if (!response.ok) {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setSession({ authenticated: false, user: null });
        return;
      }
      const payload = (await response.json()) as SessionState;
      setSession(payload);
      if (!payload.authenticated) {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
      }
    } catch {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      setToken(null);
      setSession({ authenticated: false, user: null });
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const commitAuth = React.useCallback(async (payload: AuthResponse) => {
    if (!payload.accessToken) throw new Error("Missing access token");
    localStorage.setItem(TOKEN_STORAGE_KEY, payload.accessToken);
    setToken(payload.accessToken);
    setSession({ authenticated: true, user: payload.user });
  }, []);

  const login = React.useCallback(async (email: string, password: string) => {
    const response = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password })
    });
    if (!response.ok) throw new Error(await response.text());
    await commitAuth((await response.json()) as AuthResponse);
  }, [commitAuth]);

  const register = React.useCallback(async (email: string, password: string, displayName: string) => {
    const response = await fetch(`${API_BASE_URL}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, displayName })
    });
    if (!response.ok) throw new Error(await response.text());
    await commitAuth((await response.json()) as AuthResponse);
  }, [commitAuth]);

  const logout = React.useCallback(async () => {
    if (token) {
      await apiFetch("/auth/logout", { method: "POST" }).catch(() => undefined);
    }
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setLoading(false);
    setSession({ authenticated: false, user: null });
  }, [apiFetch, token]);

  const setTokenAndRefresh = React.useCallback(async (nextToken: string) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    await loadSession(nextToken);
  }, [loadSession]);

  const value = React.useMemo(
    () => ({ ...session, loading, token, apiFetch, login, register, logout, setTokenAndRefresh }),
    [apiFetch, loading, login, logout, register, session, setTokenAndRefresh, token]
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

function formatPlays(plays: number) {
  if (plays >= 1000000) return `${(plays / 1000000).toFixed(plays % 1000000 === 0 ? 0 : 1)}M`;
  if (plays >= 1000) return `${(plays / 1000).toFixed(plays % 1000 === 0 ? 0 : 1)}K`;
  return String(plays);
}

function App() {
  const [games, setGames] = React.useState<Game[]>(fallbackGames);
  const [availableTags, setAvailableTags] = React.useState<string[]>([]);
  const { token } = useAuth();
  const [params] = useSearchParams();
  const search = params.get("q") ?? "";
  const selectedTag = params.get("tag") ?? "";

  React.useEffect(() => {
    fetchJson<Game[]>(buildGameQuery(search, selectedTag), fallbackGames, token).then(setGames);
  }, [search, selectedTag, token]);

  React.useEffect(() => {
    fetchJson<string[]>("/games/tags", [], token).then(setAvailableTags);
  }, [token]);

  const updateGame = React.useCallback((nextGame: Game) => {
    setGames((currentGames) => currentGames.map((item) => (item.id === nextGame.id ? nextGame : item)));
  }, []);

  return (
    <div className="app-shell">
      <Header />
      <Routes>
        <Route path="/" element={<Home games={games} availableTags={availableTags} search={search} selectedTag={selectedTag} />} />
        <Route path="/create" element={<ProtectedRoute><Create /></ProtectedRoute>} />
        <Route path="/games/:gameId" element={<GameDetail games={games} />} />
        <Route path="/play/:gameId" element={<PlayGame games={games} onGameUpdated={updateGame} />} />
        <Route path="/profile" element={<ProtectedRoute><Profile /></ProtectedRoute>} />
        <Route path="/auth/login" element={<LoginPage />} />
        <Route path="/auth/register" element={<RegisterPage />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
      </Routes>
    </div>
  );
}

function Header() {
  const auth = useAuth();
  const location = useLocation();
  const createTarget = auth.authenticated ? "/create" : "/auth/login?next=/create";
  const createClassName = auth.authenticated && location.pathname === "/create" ? "active" : undefined;
  return (
    <header className="topbar">
      <Link to="/" className="brand">
        <Gamepad2 size={24} />
        <span>Yahaha</span>
      </Link>
      <nav>
        <NavLink to="/">Home</NavLink>
        <Link to={createTarget} className={createClassName}>Create</Link>
        <NavLink to={auth.authenticated ? "/profile" : "/auth/login"}>
          {auth.authenticated ? "Profile" : "Log in"}
        </NavLink>
      </nav>
      <Link to={createTarget} className="create-button">
        <Plus size={18} />
        Create
      </Link>
      <nav className="mobile-tabbar" aria-label="Primary">
        <NavLink to="/"><HomeIcon size={20} /><span>Home</span></NavLink>
        <Link to={createTarget} className={createClassName}><Plus size={20} /><span>Create</span></Link>
        <NavLink to={auth.authenticated ? "/profile" : "/auth/login"}><UserRound size={20} /><span>{auth.authenticated ? "Profile" : "Log in"}</span></NavLink>
      </nav>
    </header>
  );
}

function Home({
  games,
  availableTags,
  search,
  selectedTag
}: {
  games: Game[];
  availableTags: string[];
  search: string;
  selectedTag: string;
}) {
  const auth = useAuth();
  const navigate = useNavigate();
  const sections = ["Players' Choice", "Trending", "Recommended For You", "Recently Created"];
  const isFiltering = Boolean(search || selectedTag);
  const featuredGame = games[0] ?? fallbackGames[0];

  function updateFilter(nextSearch: string, nextTag = selectedTag) {
    const query = new URLSearchParams();
    if (nextSearch.trim()) query.set("q", nextSearch.trim());
    if (nextTag.trim()) query.set("tag", nextTag.trim());
    navigate(query.toString() ? `/?${query.toString()}` : "/");
  }

  return (
    <main className="home-layout">
      <section className="arcade-spotlight">
        <Link to={`/play/${featuredGame.id}`} className="spotlight-media" aria-label={`Play ${featuredGame.title}`}>
          <img src={featuredGame.coverUrl} alt="" />
          <span className="spotlight-play"><Play size={24} /> Play</span>
        </Link>
        <div className="spotlight-copy">
          <p className="eyebrow">Featured arcade</p>
          <h1>{featuredGame.title}</h1>
          <p>{featuredGame.description}</p>
          <div className="spotlight-meta">
            <span>{formatPlays(featuredGame.plays)} plays</span>
            <span>{featuredGame.author}</span>
            <span>{featuredGame.section}</span>
          </div>
          <div className="tag-row">
            {featuredGame.tags.slice(0, 4).map((tag) => <span key={tag}>{tag}</span>)}
          </div>
          <div className="spotlight-actions">
            <Link to={`/play/${featuredGame.id}`} className="primary-action"><Play size={18} />Play now</Link>
            <Link to={auth.authenticated ? "/create" : "/auth/login?next=/create"} className="secondary-action">
              <Sparkles size={18} />
              Create your own
            </Link>
          </div>
        </div>
      </section>
      <section className="catalog-tools">
        <label className="search-box">
          <Search size={18} />
          <input
            value={search}
            onChange={(event) => updateFilter(event.target.value)}
            placeholder="Search games, creators, tags..."
          />
        </label>
        <div className="filter-tags">
          <button type="button" className={!selectedTag ? "selected" : undefined} onClick={() => updateFilter(search, "")}>
            All
          </button>
          {availableTags.map((tag) => (
            <button
              key={tag}
              type="button"
              className={selectedTag === tag ? "selected" : undefined}
              onClick={() => updateFilter(search, selectedTag === tag ? "" : tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      </section>
      {isFiltering ? (
        <GameSection title={`${games.length} result${games.length === 1 ? "" : "s"}`} games={games} layout="grid" />
      ) : (
        sections.map((section) => {
          const sectionGames = games.filter((game) => game.section === section);
          if (sectionGames.length === 0) return null;
          return <GameSection key={section} title={section} games={sectionGames} />;
        })
      )}
    </main>
  );
}

function GameSection({ title, games, layout = "rail" }: { title: string; games: Game[]; layout?: "rail" | "grid" }) {
  return (
    <section className="game-section">
      <div className="section-heading">
        <h2>{title}</h2>
        <span>{games.length} games</span>
      </div>
      <div className={layout === "grid" ? "game-grid filter-grid" : "game-grid"}>
        {games.map((game) => (
          <article className="game-card" key={game.id}>
            <Link to={`/games/${game.id}`} className="cover-link">
              <img src={game.coverUrl} alt="" />
              <span className="play-count"><Play size={14} />{formatPlays(game.plays)}</span>
            </Link>
            <div className="card-body">
              <div>
                <h3>{game.title}</h3>
                <p>@{game.author}</p>
              </div>
              <Link to={`/play/${game.id}`} className="icon-action" title={`Play ${game.title}`}>
                <Play size={18} />
              </Link>
            </div>
            <div className="tag-row">
              {game.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
            <div className="card-stats">
              <span><Heart size={14} />{formatPlays(game.likes)}</span>
              <span><Bookmark size={14} />{formatPlays(game.favorites)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function GameDetail({ games }: { games: Game[] }) {
  const { gameId } = useParams();
  const [remoteGame, setRemoteGame] = React.useState<Game | null>(null);
  const [versions, setVersions] = React.useState<GameVersionSummary[]>([]);
  const [remixStatus, setRemixStatus] = React.useState("");
  const auth = useAuth();
  const navigate = useNavigate();
  const game = remoteGame ?? games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId);

  React.useEffect(() => {
    if (!gameId) return;
    fetchJson<Game | null>(`/games/${gameId}`, null, auth.token).then((nextGame) => {
      if (nextGame) setRemoteGame(nextGame);
    });
    fetchJson<GameVersionSummary[]>(`/games/${gameId}/versions`, [], auth.token).then(setVersions);
  }, [auth.token, gameId]);

  async function updateInteraction(kind: "like" | "favorite", enabled: boolean) {
    if (!game) return;
    if (!auth.authenticated) {
      navigate(`/auth/login?next=/games/${game.id}`);
      return;
    }
    const response = await auth.apiFetch(`/games/${game.id}/${kind}`, { method: enabled ? "PUT" : "DELETE" });
    if (!response.ok) return;
    const state = (await response.json()) as GameInteractionState;
    setRemoteGame({
      ...game,
      likes: state.likes,
      favorites: state.favorites,
      likedByMe: state.likedByMe,
      favoritedByMe: state.favoritedByMe
    });
  }

  async function remixCurrentGame() {
    if (!game) return;
    if (!auth.authenticated) {
      navigate(`/auth/login?next=/games/${game.id}`);
      return;
    }
    setRemixStatus("Creating remix draft...");
    const response = await auth.apiFetch(`/games/${game.id}/remix`, { method: "POST" });
    if (!response.ok) {
      setRemixStatus("Remix failed.");
      return;
    }
    const remix = (await response.json()) as RemixResponse;
    setRemixStatus(`Draft created: ${remix.title}`);
  }

  async function switchVersion(versionId: string) {
    if (!game || !auth.authenticated) {
      navigate(`/auth/login?next=/games/${game?.id ?? gameId ?? ""}`);
      return;
    }
    setRemixStatus("Switching active version...");
    const response = await auth.apiFetch(`/games/${game.id}/versions/switch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ versionId })
    });
    if (!response.ok) {
      setRemixStatus("Version switch is only available to the creator.");
      return;
    }
    const nextVersions = (await response.json()) as GameVersionSummary[];
    setVersions(nextVersions);
    const nextGame = await fetchJson<Game | null>(`/games/${game.id}`, null, auth.token);
    if (nextGame) setRemoteGame(nextGame);
    setRemixStatus("Active version updated.");
  }

  if (!game) return <EmptyState title="Game not found" body="The selected game id is not in the local catalog." />;

  return (
    <main className="detail-layout">
      <section className="detail-hero">
        <img src={game.coverUrl} alt="" className="detail-cover" />
        <Link to={`/play/${game.id}`} className="detail-play-button">
          <Play size={28} />
        </Link>
      </section>
      <section className="detail-copy">
        <p className="eyebrow">{game.section}</p>
        <h1>{game.title}</h1>
        <p>{game.description}</p>
        <div className="meta-grid">
          <span>Author: {game.author}</span>
          <span>Plays: {formatPlays(game.plays)}</span>
          <span>Likes: {formatPlays(game.likes)}</span>
          <span>Favorites: {formatPlays(game.favorites)}</span>
          <span>Published: {new Date(game.publishedAt).toLocaleDateString()}</span>
        </div>
        <div className="tag-row">
          {game.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className="detail-actions">
          <Link to={`/play/${game.id}`} className="primary-action">
            <Play size={18} />
            Play now
          </Link>
          <button
            type="button"
            className={game.likedByMe ? "secondary-action selected" : "secondary-action"}
            onClick={() => void updateInteraction("like", !game.likedByMe)}
          >
            <Heart size={18} />
            {game.likedByMe ? "Liked" : "Like"}
          </button>
          <button
            type="button"
            className={game.favoritedByMe ? "secondary-action selected" : "secondary-action"}
            onClick={() => void updateInteraction("favorite", !game.favoritedByMe)}
          >
            <Bookmark size={18} />
            {game.favoritedByMe ? "Saved" : "Save"}
          </button>
          <button type="button" className="secondary-action" onClick={() => void remixCurrentGame()}>
            <Plus size={18} />
            Remix
          </button>
        </div>
        {remixStatus && <p className="status-panel">{remixStatus}</p>}
        <section className="version-panel">
          <h2>Versions</h2>
          {versions.length ? versions.map((version) => (
            <div className="version-row" key={version.versionId}>
              <strong>v{version.versionNo} · {version.runtime}{version.current ? " · current" : ""}</strong>
              <span>{version.buildStatus} / safety {version.safetyStatus}</span>
              <span>{new Date(version.createdAt).toLocaleString()}</span>
              {!version.current && (
                <button type="button" className="secondary-action" onClick={() => void switchVersion(version.versionId)}>
                  Switch
                </button>
              )}
            </div>
          )) : <p>No version records found.</p>}
        </section>
      </section>
    </main>
  );
}

function PlayGame({ games, onGameUpdated }: { games: Game[]; onGameUpdated: (game: Game) => void }) {
  const { gameId } = useParams();
  const [remoteGame, setRemoteGame] = React.useState<Game | null>(null);
  const game = remoteGame ?? games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId);
  const [manifest, setManifest] = React.useState<Manifest | null>(null);
  const [srcDoc, setSrcDoc] = React.useState("");
  const [loadError, setLoadError] = React.useState("");
  const frameRef = React.useRef<HTMLIFrameElement | null>(null);
  const { apiFetch, token } = useAuth();
  const anonymousId = React.useMemo(() => getAnonymousId(), []);

  const reportPlayEvent = React.useCallback((eventType: "game_view" | "game_start" | "game_end" | "game_load_error", metadata: Record<string, unknown> = {}) => {
    if (!gameId) return;
    void apiFetch("/events/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gameId,
        event: eventType,
        anonymousId,
        metadata
      })
    })
      .then((response) => {
        if (!response.ok || !["game_view", "game_start"].includes(eventType)) return null;
        return fetchJson<Game | null>(`/games/${gameId}`, null, token);
      })
      .then((nextGame) => {
        if (!nextGame) return;
        setRemoteGame(nextGame);
        onGameUpdated(nextGame);
      })
      .catch(() => undefined);
  }, [anonymousId, apiFetch, gameId, onGameUpdated, token]);

  React.useEffect(() => {
    if (!gameId || games.some((item) => item.id === gameId) || fallbackGames.some((item) => item.id === gameId)) return;
    fetchJson<Game | null>(`/games/${gameId}`, null, token).then(setRemoteGame);
  }, [gameId, games, token]);

  React.useEffect(() => {
    if (!gameId) return;
    setSrcDoc("");
    setLoadError("");
    fetchJson<Manifest | null>(`/play/${gameId}/manifest`, null, token).then(async (nextManifest) => {
      setManifest(nextManifest);
      const documentUrl = nextManifest?.documentUrl ?? nextManifest?.bundleUrl;
      if (!documentUrl) {
        setLoadError("No playable document was returned for this game.");
        return;
      }
      try {
        const response = await fetch(documentUrl.startsWith("http") ? documentUrl : `${API_BASE_URL}${documentUrl}`);
        if (!response.ok) throw new Error("Document request failed");
        setSrcDoc(preparePlayableDocument(await response.text()));
      } catch {
        setLoadError("The playable document could not be loaded.");
        reportPlayEvent("game_load_error");
      }
    });
  }, [gameId, reportPlayEvent, token]);

  React.useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const data = event.data as { source?: string; type?: string; gameId?: string; payload?: Record<string, unknown> };
      if (!gameId || event.source !== frameRef.current?.contentWindow) return;
      if (data?.source !== "yahaha-game") return;
      if (!["game_start", "game_end", "game_load_error"].includes(data.type ?? "")) return;
      reportPlayEvent(data.type as "game_start" | "game_end" | "game_load_error", data.payload ?? {});
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [gameId, reportPlayEvent]);

  React.useEffect(() => {
    function preventPageScroll(event: KeyboardEvent) {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", " ", "Spacebar"].includes(event.key)) return;
      const activeElement = document.activeElement;
      const isEditing =
        activeElement instanceof HTMLInputElement ||
        activeElement instanceof HTMLTextAreaElement ||
        activeElement instanceof HTMLSelectElement ||
        activeElement?.getAttribute("contenteditable") === "true";
      if (!isEditing) event.preventDefault();
    }
    window.addEventListener("keydown", preventPageScroll, { passive: false });
    return () => window.removeEventListener("keydown", preventPageScroll);
  }, []);

  React.useEffect(() => {
    if (!srcDoc) return;
    frameRef.current?.focus();
  }, [srcDoc]);

  if (!game) return <EmptyState title="Game not found" body="The selected game id is not in the local catalog." />;

  return (
    <main className="play-layout">
      <section className="play-header">
        <div>
          <p className="eyebrow">Now playing</p>
          <h1>{game.title}</h1>
        </div>
        <Link to={`/games/${game.id}`} className="secondary-action">Details</Link>
      </section>
      <section className="play-stage">
        <iframe
          ref={frameRef}
          className="game-frame"
          title={game.title}
          sandbox="allow-scripts"
          srcDoc={srcDoc}
          tabIndex={0}
          onLoad={() => {
            if (srcDoc) reportPlayEvent("game_view", { source: "iframe_load" });
          }}
        />
      </section>
      {loadError && <p className="form-error">{loadError}</p>}
      <p className="manifest-note">
        Runtime: {manifest?.runtime ?? "iframe-html5"} · Entry: {manifest?.entry ?? "index.html"}
      </p>
    </main>
  );
}

function Create() {
  const [message, setMessage] = React.useState("");
  const [status, setStatus] = React.useState("Checking Create configuration...");
  const [aiConfig, setAiConfig] = React.useState<AIConfigState | null>(null);
  const [baseUrl, setBaseUrl] = React.useState("http://43.106.115.130:8080/v1");
  const [model, setModel] = React.useState("gpt-5.5");
  const [apiKey, setApiKey] = React.useState("");
  const [editingConfig, setEditingConfig] = React.useState(false);
  const [llmTest, setLlmTest] = React.useState<LLMTestResult | null>(null);
  const [agentMode, setAgentMode] = React.useState<AgentMode>("chat");
  const [createType, setCreateType] = React.useState<"init" | "opt">("init");
  const [projectId, setProjectId] = React.useState("");
  const [projects, setProjects] = React.useState<CreateProject[]>([]);
  const [modeOpen, setModeOpen] = React.useState(false);
  const [job, setJob] = React.useState<CreateJob | null>(null);
  const [runSteps, setRunSteps] = React.useState<CreateRunStep[]>([]);
  const [streaming, setStreaming] = React.useState(false);
  const [planPreview, setPlanPreview] = React.useState<PlanPreview | null>(null);
  const [planDecisionBusy, setPlanDecisionBusy] = React.useState(false);
  const [decentralizedPreview, setDecentralizedPreview] = React.useState<DecentralizedPreviewResponse | null>(null);
  const [decentralizedBusy, setDecentralizedBusy] = React.useState(false);
  const [projectPreview, setProjectPreview] = React.useState<CreateProjectPreview | null>(null);
  const [previewBusy, setPreviewBusy] = React.useState(false);
  const [recentGame, setRecentGame] = React.useState<RecentGame | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [pendingImages, setPendingImages] = React.useState<PendingImage[]>([]);
  const streamAbortRef = React.useRef<AbortController | null>(null);
  const pendingImagesRef = React.useRef<PendingImage[]>([]);
  const { apiFetch, token } = useAuth();

  React.useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  React.useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
      pendingImagesRef.current.forEach((image) => URL.revokeObjectURL(image.previewUrl));
    };
  }, []);

  const loadProjects = React.useCallback(async () => {
    const projectsResponse = await apiFetch("/create/projects");
    if (projectsResponse.ok) {
      const projectPayload = (await projectsResponse.json()) as CreateProject[];
      setProjects(projectPayload);
      if (!projectId && projectPayload.length > 0) setProjectId(projectPayload[0].projectId);
    }
  }, [apiFetch, projectId]);

  const loadCreateState = React.useCallback(async () => {
    const configResponse = await apiFetch("/create/ai-config");
    if (configResponse.ok) {
      const payload = (await configResponse.json()) as AIConfigState;
      setAiConfig(payload);
      setStatus(payload.configured ? "Saved AI configuration is ready. Create generation is enabled." : "Add your AI configuration before creating.");
      setEditingConfig(!payload.configured);
    }
    const recentResponse = await apiFetch("/create/recent-game");
    if (recentResponse.ok) {
      setRecentGame((await recentResponse.json()) as RecentGame | null);
    }
    await loadProjects();
  }, [apiFetch, loadProjects]);

  React.useEffect(() => {
    void loadCreateState();
  }, [loadCreateState]);

  React.useEffect(() => {
    if (createType === "init" && !INIT_AGENT_MODES.includes(agentMode as (typeof INIT_AGENT_MODES)[number])) {
      setAgentMode("chat");
    }
    if (createType === "opt" && !OPT_AGENT_MODES.includes(agentMode as (typeof OPT_AGENT_MODES)[number])) setAgentMode("refine");
  }, [agentMode, createType]);

  async function loadProjectPreview(nextProjectId = projectId) {
    if (!nextProjectId) {
      setProjectPreview(null);
      return null;
    }
    setPreviewBusy(true);
    try {
      const response = await apiFetch(`/create/projects/${nextProjectId}/preview`);
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as CreateProjectPreview;
      setProjectPreview(payload);
      setStatus(`Loaded version ${payload.versionNo} for continue optimization.`);
      return payload;
    } catch (error) {
      setProjectPreview(null);
      setStatus(error instanceof Error ? error.message : "Project preview could not be loaded.");
      return null;
    } finally {
      setPreviewBusy(false);
    }
  }

  React.useEffect(() => {
    if (createType === "opt" && projectId) {
      void loadProjectPreview(projectId);
    } else {
      setProjectPreview(null);
    }
  }, [createType, projectId]);

  async function saveConfig(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setLlmTest(null);
    setStatus("Saving AI configuration...");
    try {
      const response = await apiFetch("/create/ai-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseUrl, model, apiKey })
      });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as AIConfigState;
      setAiConfig(payload);
      setApiKey("");
      setEditingConfig(false);
      setStatus("AI configuration saved. You can create a game now.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "AI configuration could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function testConfig() {
    setBusy(true);
    setLlmTest(null);
    setStatus("Testing LLM configuration...");
    try {
      const response = await apiFetch("/create/ai-config/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(apiKey.trim() ? { baseUrl, model, apiKey } : {})
      });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as LLMTestResult;
      setLlmTest(payload);
      setStatus(payload.ok ? "LLM configuration test passed." : payload.message);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "LLM configuration test failed.");
    } finally {
      setBusy(false);
    }
  }

  function mergeRunEvent(event: CreateRunEvent) {
    if (event.type === "heartbeat" || !event.stepNo || !event.stage || !event.status) return;
    const preview = event.metrics ? event.metrics.planPreview : undefined;
    if (event.type === "plan_ready" && isPlanPreview(preview)) {
      setPlanPreview(preview);
      setStatus("Plan is ready. Review it before generation continues.");
    }
    const decentralizedState = event.metrics ? event.metrics.previewState : undefined;
    if (event.type === "decentralized_preview_ready" && isDecentralizedPreview(decentralizedState)) {
      setDecentralizedPreview(decentralizedState);
      setStatus("Three static directions are ready. Choose one before final generation.");
    }
    const nextStep: CreateRunStep = {
      stepNo: event.stepNo,
      stage: event.stage,
      status: event.status,
      inputSummary: event.inputSummary ?? null,
      outputSummary: event.outputSummary ?? null,
      metrics: event.metrics ?? {},
      createdAt: event.createdAt ?? new Date().toISOString()
    };
    setRunSteps((current) => {
      const without = current.filter((step) => step.stepNo !== nextStep.stepNo);
      return [...without, nextStep].sort((left, right) => left.stepNo - right.stepNo);
    });
    if (event.stage?.startsWith("cover_")) {
      setStatus(runStageLabel(event.stage));
    } else if (event.stage?.startsWith("decentralized_")) {
      setStatus(runStageLabel(event.stage));
    } else if (event.type === "llm_call") {
      setStatus("LLM responded. Updating generation timeline...");
    } else if (event.type === "tool_call") {
      setStatus(`Tool step completed: ${event.metrics?.toolName ?? event.stage}`);
    } else if (event.type === "error") {
      setStatus(event.outputSummary || "Create generation failed.");
    } else if (event.type === "done") {
      setStatus("Create generation completed.");
    } else if (event.outputSummary) {
      setStatus(event.outputSummary);
    }
  }

  async function loadFinalJob(jobId: string) {
    const response = await apiFetch(`/create/jobs/${jobId}`);
    if (response.ok) {
      const payload = (await response.json()) as CreateJob;
      setJob(payload);
      await loadCreateState();
    }
  }

  async function connectRunEvents(runId: string, jobId: string) {
    streamAbortRef.current?.abort();
    const controller = new AbortController();
    streamAbortRef.current = controller;
    setStreaming(true);
    try {
      const response = await fetch(`${API_BASE_URL}/create/runs/${runId}/events`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal: controller.signal
      });
      if (!response.ok || !response.body) {
        setStatus("Run event stream could not be opened. Use Run steps to refresh.");
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const dataLine = chunk.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const event = JSON.parse(dataLine.slice(6)) as CreateRunEvent;
          mergeRunEvent(event);
          if (event.type === "done") {
            await loadFinalJob(jobId);
            return;
          }
          if (event.type === "error") {
            await loadFinalJob(jobId);
            return;
          }
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setStatus(error instanceof Error ? error.message : "Run event stream interrupted.");
      }
    } finally {
      setStreaming(false);
    }
  }

  function addImages(files: FileList | null) {
    if (!files?.length) return;
    const accepted = Array.from(files).filter((file) => file.type.startsWith("image/"));
    if (accepted.length === 0) {
      setStatus("Only image files can be attached to Create.");
      return;
    }
    setPendingImages((current) => [
      ...current,
      ...accepted.map((file) => ({
        id: crypto.randomUUID(),
        file,
        previewUrl: URL.createObjectURL(file)
      }))
    ]);
    setStatus(`${accepted.length} image${accepted.length === 1 ? "" : "s"} attached for multimodal Create.`);
  }

  function removeImage(imageId: string) {
    setPendingImages((current) => {
      const removed = current.find((image) => image.id === imageId);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((image) => image.id !== imageId);
    });
  }

  async function uploadPendingImages() {
    const uploaded: CreateInputAsset[] = [];
    const nextImages: PendingImage[] = [];
    for (const image of pendingImagesRef.current) {
      if (image.uploaded) {
        uploaded.push(image.uploaded);
        nextImages.push(image);
        continue;
      }
      const formData = new FormData();
      formData.append("file", image.file);
      const response = await apiFetch("/uploads", { method: "POST", body: formData });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const asset = (await response.json()) as CreateInputAsset;
      uploaded.push(asset);
      nextImages.push({ ...image, uploaded: asset });
    }
    setPendingImages(nextImages);
    return uploaded;
  }

  async function cleanupUploadedImages(inputAssets: CreateInputAsset[]) {
    if (inputAssets.length === 0) return;
    await Promise.allSettled(inputAssets.map((asset) => apiFetch(`/uploads/${asset.assetId}`, { method: "DELETE" })));
    setPendingImages((current) => current.map((image) => ({ ...image, uploaded: undefined })));
  }

  async function submitJob(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setLlmTest(null);
    setStatus("Starting Create run...");
    setJob(null);
    setRunSteps([]);
    setPlanPreview(null);
    setDecentralizedPreview(null);
    if (createType === "opt" && !projectId) {
      setStatus("Select a project before continuing optimization.");
      setBusy(false);
      return;
    }
    const requestAgentMode: AgentMode = agentMode;
    let inputAssets: CreateInputAsset[] = [];
    try {
      if (pendingImagesRef.current.length > 0) {
        setStatus("Uploading image inputs...");
        inputAssets = await uploadPendingImages();
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Image upload failed.");
      setBusy(false);
      return;
    }
    setStatus("Starting Create run...");
    const response = await apiFetch("/create/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: message,
        files: [],
        inputAssets,
        agentMode: requestAgentMode,
        createType,
        projectId: createType === "opt" ? projectId : undefined
      })
    });
    if (!response.ok) {
      const error = await readApiError(response);
      await cleanupUploadedImages(inputAssets);
      if (response.status === 409) {
        setStatus("AI configuration is required before creating.");
        setAiConfig({ authenticated: true, configured: false, provider: "fighting", staticGeneration: false });
        setEditingConfig(true);
      } else if (error.code === "LLM_CONFIG_INVALID" && error.llm) {
        setLlmTest(error.llm);
        setEditingConfig(true);
        setStatus(error.message);
      } else if (response.status === 401) {
        setStatus("Please log in again before creating a game.");
      } else {
        setStatus(error.message);
      }
      setBusy(false);
      return;
    }
    const payload = (await response.json()) as CreateJob;
    setJob(payload);
    if (payload.projectId) setProjectId(payload.projectId);
    setStatus(`Job ${payload.id} started. Streaming generation steps...`);
    setBusy(false);
    if (payload.runId) {
      void connectRunEvents(payload.runId, payload.id);
    }
  }

  async function loadRunSteps() {
    if (!job?.runId) return;
    setBusy(true);
    setStatus("Loading run steps...");
    try {
      const response = await apiFetch(`/create/runs/${job.runId}/steps`);
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      setRunSteps((await response.json()) as CreateRunStep[]);
      setStatus("Run steps loaded.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Run steps could not be loaded.");
    } finally {
      setBusy(false);
    }
  }

  async function publishDraft() {
    if (!job?.id) return;
    setBusy(true);
    setStatus("Publishing game...");
    try {
      const response = await apiFetch(`/create/jobs/${job.id}/publish`, { method: "POST" });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as CreateJob;
      setJob(payload);
      setStatus("Game published. It is now visible on Home and Play is available.");
      await loadProjects();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Publish failed.");
    } finally {
      setBusy(false);
    }
  }

  function continueCurrentProject() {
    const nextProjectId = job?.projectId ?? projectId;
    if (!nextProjectId) return;
    setCreateType("opt");
    setAgentMode("refine");
    setProjectId(nextProjectId);
    setMessage("");
    setJob(null);
    setRunSteps([]);
    setPlanPreview(null);
    setDecentralizedPreview(null);
    setStatus("Continue optimize selected. Add the next request for this project.");
    void loadProjectPreview(nextProjectId);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function loadPlanPreview(runId: string) {
    const response = await apiFetch(`/create/runs/${runId}/plan-preview`);
    if (!response.ok) {
      const error = await readApiError(response);
      throw new Error(error.message);
    }
    const payload = (await response.json()) as PlanPreviewResponse;
    setPlanPreview(payload.planPreview);
    return payload.planPreview;
  }

  async function decidePlan(decision: "accepted" | "rejected") {
    if (!job?.runId) return;
    setPlanDecisionBusy(true);
    setStatus(decision === "accepted" ? "Accepting plan and continuing generation..." : "Rejecting plan...");
    try {
      const response = await apiFetch(`/create/runs/${job.runId}/plan-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision })
      });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as CreateJob;
      setJob(payload);
      if (decision === "rejected") {
        streamAbortRef.current?.abort();
        setStreaming(false);
        setStatus("Plan rejected. This run was canceled and kept for maintainer review.");
        await loadRunSteps();
      } else {
        setStatus("Plan accepted. Continuing generation...");
        setPlanPreview(null);
        if (payload.runId) void connectRunEvents(payload.runId, payload.id);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Plan decision failed.");
    } finally {
      setPlanDecisionBusy(false);
    }
  }

  async function loadDecentralizedPreviews(runId: string) {
    const response = await apiFetch(`/create/runs/${runId}/decentralized-previews`);
    if (!response.ok) {
      const error = await readApiError(response);
      throw new Error(error.message);
    }
    const payload = (await response.json()) as DecentralizedPreviewResponse;
    setDecentralizedPreview(payload);
    return payload;
  }

  async function selectDecentralizedCandidate(candidateId: string) {
    if (!job?.runId) return;
    setDecentralizedBusy(true);
    setStatus("Selecting decentralized direction...");
    try {
      const response = await apiFetch(`/create/runs/${job.runId}/decentralized-selection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidateId })
      });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as DecentralizedPreviewResponse;
      setDecentralizedPreview(payload);
      setStatus("Direction selected. Confirm to continue final generation.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Direction selection failed.");
    } finally {
      setDecentralizedBusy(false);
    }
  }

  async function confirmDecentralized(decision: "accepted" | "rejected") {
    if (!job?.runId) return;
    setDecentralizedBusy(true);
    setStatus(decision === "accepted" ? "Confirming direction and starting final generation..." : "Rejecting decentralized directions...");
    try {
      const response = await apiFetch(`/create/runs/${job.runId}/decentralized-confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision })
      });
      if (!response.ok) {
        const error = await readApiError(response);
        throw new Error(error.message);
      }
      const payload = (await response.json()) as CreateJob;
      setJob(payload);
      if (decision === "rejected") {
        streamAbortRef.current?.abort();
        setStreaming(false);
        setStatus("Directions rejected. This run was canceled and kept for maintainer review.");
        await loadRunSteps();
      } else {
        setStatus("Direction confirmed. Final game generation is running...");
        if (payload.runId) void connectRunEvents(payload.runId, payload.id);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Decentralized confirmation failed.");
    } finally {
      setDecentralizedBusy(false);
    }
  }

  return (
    <main className="create-layout">
      <section>
        <p className="eyebrow">Create</p>
        <h1>Describe a game idea</h1>
        <p>Configure base_url, model, and api_key once. The backend stores and uses the saved configuration without sending it back to the browser.</p>
      </section>
      {aiConfig && (!aiConfig.configured || editingConfig) && (
        <form className="prompt-panel" onSubmit={saveConfig}>
          <label>
            <span>base_url</span>
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required />
          </label>
          <label>
            <span>model</span>
            <input value={model} onChange={(event) => setModel(event.target.value)} required />
          </label>
          <label>
            <span>api_key</span>
            <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" required />
          </label>
          {llmTest && (
            <div className={llmTest.ok ? "test-report success" : "test-report error"}>
              <strong>{llmTest.code}</strong>
              <span>{llmTest.message}</span>
              {typeof llmTest.details.providerMessage === "string" && <span>{llmTest.details.providerMessage}</span>}
            </div>
          )}
          <div className="form-actions">
            <button type="button" disabled={busy || (!aiConfig.configured && !apiKey.trim())} onClick={testConfig}>
              {apiKey.trim() ? "Test new settings" : "Test saved settings"}
            </button>
            <button type="submit" disabled={busy || !baseUrl.trim() || !model.trim() || !apiKey.trim()}>Save AI config</button>
            {aiConfig.configured && (
              <button
                type="button"
                className="ghost-button"
                disabled={busy}
                onClick={() => {
                  setEditingConfig(false);
                  setApiKey("");
                  setLlmTest(null);
                  setStatus("Saved AI configuration is ready. Create generation is enabled.");
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
      {aiConfig?.configured && !editingConfig && (
        <section className="status-panel">
          <span>Saved AI configuration is ready. Secret values are kept on the backend.</span>
          <button
            type="button"
            className="inline-action"
            onClick={() => {
              setEditingConfig(true);
              setLlmTest(null);
              setApiKey("");
              setStatus("Enter a new base_url, model, and api_key only if you want to replace the saved configuration.");
            }}
          >
            <Settings size={16} />
            Reconfigure
          </button>
        </section>
      )}
      {aiConfig?.staticGeneration && (
        <section className="static-warning">
          Current backend is using static test generation. Set CREATE_STATIC_GENERATION=false and restart the API to use real LLM generation.
        </section>
      )}
      {recentGame && (
        <section className="result-panel">
          <div>
            <span>Recent game</span>
            <strong>{recentGame.title}</strong>
          </div>
          <Link to={recentGame.playUrl} className="secondary-action">Play recent</Link>
        </section>
      )}
      <form className="prompt-panel" onSubmit={submitJob}>
        <div className="create-type-row">
          <button
            type="button"
            className={createType === "init" ? "selected" : undefined}
            onClick={() => {
              setCreateType("init");
              setAgentMode("chat");
              setProjectPreview(null);
            }}
          >
            Initial create
          </button>
          <button
            type="button"
            className={createType === "opt" ? "selected" : undefined}
            onClick={() => {
              setCreateType("opt");
              setAgentMode("refine");
              if (projectId) void loadProjectPreview(projectId);
            }}
            disabled={projects.length === 0}
          >
            Continue optimize
          </button>
        </div>
        {createType === "opt" && (
          <label>
            <span>project_id</span>
            <select
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                void loadProjectPreview(event.target.value);
              }}
              required
            >
              {projects.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.title} · {project.publishStatus ?? "no draft"}{project.currentVersionNo ? ` · v${project.currentVersionNo}` : ""} · {project.projectId}
                </option>
              ))}
            </select>
          </label>
        )}
        {createType === "opt" && (
          <section className="refine-preview-panel">
            <div className="plan-review-header">
              <div>
                <span>Current version preview</span>
                <strong>{projectPreview ? `${projectPreview.title} · v${projectPreview.versionNo}` : "Select a project with an existing game"}</strong>
              </div>
              <button type="button" className="inline-action" disabled={previewBusy || !projectId} onClick={() => void loadProjectPreview(projectId)}>
                {previewBusy ? "Loading..." : "Refresh preview"}
              </button>
            </div>
            {projectPreview ? (
              <div className="refine-preview-frame">
                <iframe
                  title={`${projectPreview.title} playable preview`}
                  srcDoc={preparePlayableDocument(projectPreview.html)}
                  sandbox="allow-scripts"
                  tabIndex={0}
                />
              </div>
            ) : (
              <p className="muted-copy">Create and save a draft first, then continue optimization from the latest version.</p>
            )}
            <small>This is a playable creator preview, including unpublished drafts. Click inside the frame before using keyboard controls.</small>
          </section>
        )}
        <div className="mode-picker">
          <button type="button" className="mode-toggle" onClick={() => setModeOpen((value) => !value)}>
            Mode: {agentMode}
          </button>
          {modeOpen && (
            <div className="mode-options">
              {(createType === "init" ? INIT_AGENT_MODES : OPT_AGENT_MODES).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={agentMode === mode ? "selected" : undefined}
                  onClick={() => {
                    setAgentMode(mode);
                    setModeOpen(false);
                  }}
                >
                  {mode}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="multimodal-composer">
          {pendingImages.length > 0 && (
            <div className="image-preview-list">
              {pendingImages.map((image) => (
                <div className="image-preview" key={image.id}>
                  <img src={image.previewUrl} alt={image.file.name} />
                  <button type="button" onClick={() => removeImage(image.id)} disabled={busy || streaming}>
                    Remove
                  </button>
                  {image.uploaded && <span>Uploaded</span>}
                </div>
              ))}
            </div>
          )}
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="A neon puzzle game where players connect constellations..."
            disabled={!aiConfig?.configured || editingConfig || busy}
          />
          <div className="composer-actions">
            <label className="image-upload-button">
              Add image
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                multiple
                disabled={!aiConfig?.configured || editingConfig || busy || streaming}
                onChange={(event) => {
                  addImages(event.target.files);
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <button type="submit" disabled={!aiConfig?.configured || editingConfig || busy || streaming}>
              {streaming ? "Creating..." : "Create game"}
            </button>
          </div>
        </div>
      </form>
      <div className="status-panel">{status}</div>
      {job?.agentMode === "plan" && job.runId && !planPreview && (
        <section className="status-panel">
          <span>Waiting for plan preview.</span>
          <button type="button" className="inline-action" disabled={busy || planDecisionBusy} onClick={() => void loadPlanPreview(job.runId!)}>
            Refresh plan
          </button>
        </section>
      )}
      {job?.agentMode === "decentralized" && job.runId && !decentralizedPreview && (
        <section className="status-panel">
          <span>Generating three static creative directions.</span>
          <button
            type="button"
            className="inline-action"
            disabled={busy || decentralizedBusy}
            onClick={() => void loadDecentralizedPreviews(job.runId!)}
          >
            Refresh previews
          </button>
        </section>
      )}
      {decentralizedPreview && (
        <section className="decentralized-review-panel">
          <div className="plan-review-header">
            <div>
              <span>Decentralized preview</span>
              <strong>Choose one static direction before final generation</strong>
            </div>
            <div className="form-actions">
              <button type="button" disabled={decentralizedBusy} onClick={() => void confirmDecentralized("rejected")}>Reject all</button>
              <button
                type="button"
                disabled={decentralizedBusy || !decentralizedPreview.selectedCandidateId}
                onClick={() => void confirmDecentralized("accepted")}
              >
                Confirm direction
              </button>
            </div>
          </div>
          <div className="decentralized-candidate-grid">
            {decentralizedPreview.candidates.map((candidate) => {
              const selected = decentralizedPreview.selectedCandidateId === candidate.candidateId;
              return (
                <button
                  type="button"
                  key={candidate.candidateId}
                  className={selected ? "decentralized-candidate selected" : "decentralized-candidate"}
                  disabled={decentralizedBusy}
                  onClick={() => void selectDecentralizedCandidate(candidate.candidateId)}
                >
                  <div className="decentralized-preview-frame">
                    <iframe title={candidate.title} srcDoc={candidate.staticHtml} sandbox="allow-scripts" />
                  </div>
                  <div className="decentralized-candidate-copy">
                    <span>{candidate.expertRole} · {candidate.expertDomain}</span>
                    <strong>{candidate.title}</strong>
                    <p>{candidate.conceptSummary}</p>
                    <small>{candidate.expertIntro}</small>
                    <div className="tag-row">
                      {candidate.styleTags.map((tag) => <em key={`${candidate.candidateId}-${tag}`}>{tag}</em>)}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
          <p className="manifest-note">Static previews are intentionally non-playable. Selecting a card only sets the creative direction.</p>
        </section>
      )}
      {planPreview && (
        <section className="plan-review-panel">
          <div className="plan-review-header">
            <div>
              <span>Plan review</span>
              <strong>Review the plan before generation continues</strong>
            </div>
            <div className="form-actions">
              <button type="button" disabled={planDecisionBusy} onClick={() => void decidePlan("rejected")}>Reject plan</button>
              <button type="button" disabled={planDecisionBusy} onClick={() => void decidePlan("accepted")}>Accept plan and continue</button>
            </div>
          </div>
          <div className="plan-step-grid">
            {planPreview.plan.map((step) => (
              <div className="plan-step-card" key={step.id}>
                <span>{step.id} · {step.toolFamily}</span>
                <strong>{step.title}</strong>
                <p>{step.goal}</p>
                <small>{step.expectedOutput}</small>
                {step.acceptanceCheckRefs.length > 0 && <small>Checks: {step.acceptanceCheckRefs.join(", ")}</small>}
              </div>
            ))}
          </div>
          <div className="plan-review-columns">
            <div>
              <strong>Acceptance checks</strong>
              {planPreview.acceptanceChecks.map((check) => (
                <p key={check.id}>
                  <span>{check.severity.toUpperCase()} · {check.type}</span><br />
                  {check.description}
                </p>
              ))}
            </div>
            <div>
              <strong>Risks</strong>
              {planPreview.risks.map((risk, index) => <p key={`${risk}-${index}`}>{risk}</p>)}
              {planPreview.normalizationWarnings && planPreview.normalizationWarnings.length > 0 && (
                <small>Warnings: {planPreview.normalizationWarnings.join(", ")}</small>
              )}
            </div>
          </div>
        </section>
      )}
      {job && (
        <section className="job-panel">
          <div className="result-panel">
            <div>
              <span>Generated game</span>
              <strong>{job.gameSlug ?? job.id}</strong>
              {job.projectId && <span>Project: {job.projectId}</span>}
              {job.versionNo && <span>Version: v{job.versionNo}</span>}
              {job.publishStatus && <span>Status: {job.publishStatus} · {job.visibility ?? "private"}</span>}
              {job.runId && <span>Run: {job.runId}</span>}
              {job.taskId && <span>Task: {job.taskId}</span>}
              <span>Mode: {job.agentMode ?? agentMode}</span>
              {streaming && <span>Streaming run events...</span>}
            </div>
            <div className="result-actions">
              {job.runId && <button type="button" className="secondary-action" disabled={busy} onClick={loadRunSteps}>Run steps</button>}
              {job.status === "completed" && job.publishStatus !== "published" && (
                <>
                  <button type="button" className="secondary-action" disabled={busy} onClick={continueCurrentProject}>Continue optimize</button>
                  <button type="button" className="primary-action" disabled={busy} onClick={() => void publishDraft()}>Publish</button>
                </>
              )}
              {job.playUrl && job.publishStatus === "published" && <Link to={job.playUrl} className="primary-action"><Play size={18} />Play now</Link>}
            </div>
          </div>
          {job.logs.length > 0 && <div className="log-list">
            {job.logs.map((log) => (
              <div key={`${log.stage}-${log.message}`}>
                <span>{log.stage} · {log.status}</span>
                <p>{log.message}</p>
              </div>
            ))}
          </div>}
          {runSteps.length > 0 && (
            <div className="run-step-list">
              {runSteps.map((step) => {
                const outputTokens = step.metrics.tokenUsage && typeof step.metrics.tokenUsage === "object"
                  ? (step.metrics.tokenUsage as Record<string, unknown>).outputTokens
                  : step.metrics.outputTokens;
                return (
                  <div key={step.stepNo}>
                    <span>#{step.stepNo} {runStageLabel(step.stage)} · {step.status}</span>
                    {step.inputSummary && <p>{step.inputSummary}</p>}
                    {(step.stage === "llm_call" || step.stage === "cover_llm_call") && (
                      <small>
                        prefix words {String(step.metrics.prefixEnglishWords ?? "-")} · 中文 {String(step.metrics.prefixChineseChars ?? "-")} · output tokens {String(outputTokens ?? "-")}
                      </small>
                    )}
                    {step.stage === "cover_uploaded" && (
                      <small>
                        {String(step.metrics.contentType ?? "-")} · {String(step.metrics.sizeBytes ?? "-")} bytes · {String(step.metrics.objectKey ?? "-")}
                      </small>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}
    </main>
  );
}

function Profile() {
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth.user;
  const [activity, setActivity] = React.useState<ProfileActivity | null>(null);
  const [selectedProjectId, setSelectedProjectId] = React.useState<string | null>(null);
  const [projectDetail, setProjectDetail] = React.useState<ProfileProjectDetail | null>(null);
  const [expandedRunId, setExpandedRunId] = React.useState<string | null>(null);
  const [profileStatus, setProfileStatus] = React.useState("");
  const { apiFetch } = auth;

  const loadProfileActivity = React.useCallback(async () => {
    if (!auth.authenticated) return;
    const response = await apiFetch("/profile/activity");
    if (!response.ok) return;
    const payload = (await response.json()) as ProfileActivity;
    setActivity(payload);
    setSelectedProjectId((current) => {
      if (current && payload.projects.some((project) => project.projectId === current)) return current;
      return payload.projects[0]?.projectId ?? null;
    });
  }, [apiFetch, auth.authenticated]);

  const loadProjectDetail = React.useCallback(async (projectId: string) => {
    const response = await apiFetch(`/profile/projects/${projectId}`);
    if (!response.ok) return;
    setProjectDetail((await response.json()) as ProfileProjectDetail);
    setExpandedRunId(null);
  }, [apiFetch]);

  React.useEffect(() => {
    void loadProfileActivity();
  }, [loadProfileActivity]);

  React.useEffect(() => {
    if (!selectedProjectId) {
      setProjectDetail(null);
      return;
    }
    void loadProjectDetail(selectedProjectId);
  }, [loadProjectDetail, selectedProjectId]);

  if (!user) return null;

  async function handleLogout() {
    await auth.logout();
    navigate("/auth/login");
  }

  async function deleteSelectedProject() {
    const projectId = projectDetail?.project.projectId;
    if (!projectId) return;
    const hasPlayableGame = Boolean(projectDetail?.project.gameSlug);
    const confirmed = window.confirm(
      hasPlayableGame
        ? "Delete this project and remove its playable game from Home, detail, and Play? Run logs will be preserved for review."
        : "Delete this failed or unpublished project from your Profile? Run logs will be preserved for maintainer review."
    );
    if (!confirmed) return;
    setProfileStatus("Deleting project while preserving run logs...");
    const response = await apiFetch(`/create/projects/${projectId}`, { method: "DELETE" });
    if (!response.ok) {
      setProfileStatus("Delete failed. Only the creator can delete this project.");
      return;
    }
    const payload = (await response.json()) as CreateProjectDeleteResult;
    setProfileStatus(payload.gameSlug ? "Project and game deleted. Run logs remain available to maintainers." : "Project deleted. Run logs remain available to maintainers.");
    setProjectDetail(null);
    setSelectedProjectId(null);
    await loadProfileActivity();
  }

  return (
    <main className="profile-layout">
      <section className="profile-hero">
        {user.avatarUrl ? <img src={user.avatarUrl} alt="" className="avatar" /> : <UserRound size={42} />}
        <div>
          <p className="eyebrow">Profile</p>
          <h1>{user.displayName}</h1>
          <p>Your account is ready for protected Create workflows.</p>
        </div>
      </section>
      <section className="profile-grid">
        <div><span>User ID</span><strong>{user.id}</strong></div>
        <div><span>Email</span><strong>{user.email ?? "Not provided"}</strong></div>
        <div><span>Role</span><strong>{user.role}</strong></div>
        <div><span>Last sign in</span><strong>{user.lastLoginAt ? new Date(user.lastLoginAt).toLocaleString() : "Current session"}</strong></div>
      </section>
      {user.role === "admin" && <MaintainerPanel apiFetch={apiFetch} />}
      {activity?.recentPlays.length ? (
        <GameSection title="Recent plays" games={activity.recentPlays.map((record) => record.game)} />
      ) : (
        <section className="status-panel">No recent play history yet.</section>
      )}
      <section className="profile-projects">
        <div className="project-index">
          <div>
            <p className="eyebrow">Projects</p>
            <h2>Created game projects</h2>
          </div>
          {activity?.projects.length ? (
            activity.projects.map((project) => (
              <button
                type="button"
                key={project.projectId}
                className={selectedProjectId === project.projectId ? "selected" : undefined}
                onClick={() => setSelectedProjectId(project.projectId)}
              >
                <strong>{project.title}</strong>
                <span>{project.latestRunStatus ?? project.status} · {new Date(project.updatedAt).toLocaleDateString()}</span>
              </button>
            ))
          ) : (
            <p>No Create projects yet.</p>
          )}
        </div>
        <div className="project-detail-panel">
          {projectDetail ? (
            <>
              <div>
                <p className="eyebrow">Project detail</p>
                <h2>{projectDetail.project.title}</h2>
              </div>
              {profileStatus && <section className="status-panel">{profileStatus}</section>}
              {projectDetail.game ? (
                <>
                  <GameSection title="Project game" games={[projectDetail.game]} />
                </>
              ) : (
                <section className="status-panel">This game is deleted or not published. Run logs are preserved below.</section>
              )}
              <div className="project-danger-zone">
                <div>
                  <strong>Delete project</strong>
                  <p>Removes this project from your Profile{projectDetail.project.gameSlug ? " and removes the playable game from public access" : ""}. Run logs stay available for maintainer review.</p>
                </div>
                <button type="button" className="danger-action" onClick={() => void deleteSelectedProject()}>
                  Delete project
                </button>
              </div>
              <div className="run-feedback-list">
                {projectDetail.runs.map((run) => {
                  const expanded = expandedRunId === run.runId;
                  return (
                    <button
                      type="button"
                      key={run.runId}
                      className="run-feedback-item"
                      onClick={() => setExpandedRunId(expanded ? null : run.runId)}
                    >
                      <span>{run.createType} · {run.agentMode} · {run.status}</span>
                      <strong>{run.promptSummary || "Prompt unavailable"}</strong>
                      <p>{run.llmSummary || "LLM feedback unavailable"}</p>
                      {expanded && (
                        <div className="run-feedback-full">
                          <div className="run-meta-row">
                            <span>Created {new Date(run.createdAt).toLocaleString()}</span>
                            <span>{run.completedAt ? `Completed ${new Date(run.completedAt).toLocaleString()}` : "Still running or not completed"}</span>
                          </div>
                          <small>Prompt</small>
                          <pre>{run.promptFull || "No prompt stored."}</pre>
                          {run.steps.length > 0 ? (
                            <div className="run-timeline">
                              {run.steps.map((step) => (
                                <div className={`run-step-record ${step.recordType}`} key={`${run.runId}-${step.stepNo}`}>
                                  <div className="run-step-heading">
                                    <span>#{step.stepNo} {runStageLabel(step.stage)}</span>
                                    <strong>{runRecordTypeLabel(step.recordType)} · {step.status}</strong>
                                  </div>
                                  {step.inputSummary && <p>{step.inputSummary}</p>}
                                  {step.outputSummary && <p>{step.outputSummary}</p>}
                                  {step.recordType === "llm" && (
                                    <div className="run-step-metrics">
                                      <span>output tokens {metricText(step.metrics, "outputTokens")}</span>
                                      <span>prompt EN {metricText(step.metrics, "promptEnglishWords")}</span>
                                      <span>prompt 中文 {metricText(step.metrics, "promptChineseChars")}</span>
                                    </div>
                                  )}
                                  {step.recordType === "tool" && (
                                    <div className="run-step-metrics">
                                      <span>tool {metricText(step.metrics, "toolName")}</span>
                                      <span>ok {metricText(step.metrics, "ok")}</span>
                                      <span>files {metricText(step.metrics, "files")}</span>
                                    </div>
                                  )}
                                  {step.recordType === "error" && (
                                    <pre>{JSON.stringify(step.metrics, null, 2)}</pre>
                                  )}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <section className="status-panel">暂无详细 run 记录</section>
                          )}
                          {!run.steps.length && (
                            <>
                              <small>LLM feedback</small>
                              <pre>{run.llmFull || "No LLM feedback stored."}</pre>
                            </>
                          )}
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </>
          ) : (
            <section className="status-panel">Select a project to inspect prompts and LLM feedback.</section>
          )}
        </div>
      </section>
      <button type="button" className="secondary-action logout-action" onClick={handleLogout}>
        <LogOut size={18} />
        Log out
      </button>
    </main>
  );
}

function MaintainerPanel({ apiFetch }: { apiFetch: (path: string, init?: RequestInit) => Promise<Response> }) {
  const [overview, setOverview] = React.useState<MaintenanceOverview | null>(null);
  const [failedRuns, setFailedRuns] = React.useState<MaintenanceCreateRun[]>([]);
  const [jobs, setJobs] = React.useState<MaintenanceJob[]>([]);
  const [games, setGames] = React.useState<MaintenanceGame[]>([]);
  const [assets, setAssets] = React.useState<MaintenanceAsset[]>([]);
  const [status, setStatus] = React.useState("");

  const loadMaintenance = React.useCallback(async () => {
    setStatus("Loading maintainer data...");
    try {
      const [overviewResponse, failedRunsResponse, jobsResponse, gamesResponse, assetsResponse] = await Promise.all([
        apiFetch("/maintenance/overview"),
        apiFetch("/maintenance/create-runs/failed?limit=12"),
        apiFetch("/maintenance/jobs?limit=8"),
        apiFetch("/maintenance/games?limit=8"),
        apiFetch("/maintenance/assets?limit=8")
      ]);
      if (!overviewResponse.ok || !failedRunsResponse.ok || !jobsResponse.ok || !gamesResponse.ok || !assetsResponse.ok) {
        setStatus("Maintainer data is unavailable.");
        return;
      }
      setOverview((await overviewResponse.json()) as MaintenanceOverview);
      setFailedRuns((await failedRunsResponse.json()) as MaintenanceCreateRun[]);
      setJobs((await jobsResponse.json()) as MaintenanceJob[]);
      setGames((await gamesResponse.json()) as MaintenanceGame[]);
      setAssets((await assetsResponse.json()) as MaintenanceAsset[]);
      setStatus("");
    } catch {
      setStatus("Maintainer data is unavailable.");
    }
  }, [apiFetch]);

  React.useEffect(() => {
    void loadMaintenance();
  }, [loadMaintenance]);

  async function patchGame(gameId: string, body: Record<string, string>) {
    setStatus("Updating game metadata...");
    const response = await apiFetch(`/maintenance/games/${gameId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      setStatus("Game update failed.");
      return;
    }
    await loadMaintenance();
  }

  async function rejectGame(gameId: string) {
    setStatus("Rejecting unsafe game...");
    const response = await apiFetch(`/maintenance/games/${gameId}/moderate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "rejected", reason: "Rejected by platform maintainer" })
    });
    if (!response.ok) {
      setStatus("Moderation failed.");
      return;
    }
    await loadMaintenance();
  }

  async function markJobReviewed(jobId: string) {
    setStatus("Marking job reviewed...");
    const response = await apiFetch(`/maintenance/jobs/${jobId}/mark-reviewed`, { method: "POST" });
    if (!response.ok) {
      setStatus("Review update failed.");
      return;
    }
    await loadMaintenance();
  }

  async function retryJob(jobId: string) {
    setStatus("Retrying failed Create job...");
    const response = await apiFetch(`/maintenance/jobs/${jobId}/retry`, { method: "POST" });
    if (!response.ok) {
      setStatus("Retry failed. Check that the original creator still has AI settings.");
      return;
    }
    await loadMaintenance();
  }

  async function deleteAsset(assetId: string) {
    setStatus("Deleting asset...");
    const response = await apiFetch(`/maintenance/assets/${assetId}`, { method: "DELETE" });
    if (!response.ok) {
      setStatus("Asset delete failed. It may be referenced by a published game.");
      return;
    }
    await loadMaintenance();
  }

  return (
    <section className="maintainer-panel">
      <div className="maintainer-header">
        <div>
          <p className="eyebrow">Maintainer</p>
          <h2>Platform operations</h2>
        </div>
        <button type="button" className="secondary-action" onClick={() => void loadMaintenance()}>
          Refresh
        </button>
      </div>
      {status && <p className="maintainer-status">{status}</p>}
      <div className="maintainer-stats">
        <div><span>Failed 24h</span><strong>{overview?.failedJobsLast24h ?? "-"}</strong></div>
        <div><span>Pending reviews</span><strong>{overview?.pendingReviews ?? "-"}</strong></div>
        <div><span>Public games</span><strong>{overview?.publicGames ?? "-"}</strong></div>
        <div><span>OSS assets</span><strong>{overview ? `${overview.assetsTotal} / ${formatBytes(overview.assetsBytes)}` : "-"}</strong></div>
      </div>
      <div className="maintainer-sections">
        <div className="maintainer-card wide">
          <h3>Failed Create runs</h3>
          {failedRuns.length ? (
            <div className="failed-run-list">
              {failedRuns.map((run) => (
                <div className="failed-run-card" key={run.runId}>
                  <div className="failed-run-summary">
                    <div>
                      <strong>{run.createType} · {run.agentMode} · {run.status}</strong>
                      <p>{run.projectTitle ?? "Untitled project"} · {run.creatorEmail ?? "unknown creator"}</p>
                      <span>{run.errorCode ?? run.jobStatus ?? "failed"} {run.errorMessage ?? run.promptSummary}</span>
                    </div>
                    <div className="failed-run-metrics">
                      <span>output tokens {run.totalOutputTokens}</span>
                      <span>steps {run.steps.length}</span>
                      <span>{new Date(run.startedAt).toLocaleString()}</span>
                    </div>
                  </div>
                  <div className="run-path-box">
                    {run.steps.length ? run.steps.map((step) => (
                      <div className="run-path-step" key={`${run.runId}-${step.stepNo}`}>
                        <div>
                          <strong>#{step.stepNo} {runStageLabel(step.stage)}</strong>
                          <span>{step.status} · tokens {step.outputTokens ?? "-"}</span>
                        </div>
                        {step.inputSummary && <p>{step.inputSummary}</p>}
                        {step.outputSummary && <p>{step.outputSummary}</p>}
                        <small>{formatStepMetrics(step.metrics)}</small>
                      </div>
                    )) : (
                      <p>No run path steps recorded.</p>
                    )}
                  </div>
                  {run.jobId && (
                    <div className="maintainer-actions">
                      <button type="button" onClick={() => void retryJob(run.jobId!)}>Retry</button>
                      <button type="button" onClick={() => void markJobReviewed(run.jobId!)}>Mark reviewed</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : <p>No failed Create runs found.</p>}
        </div>
        <div className="maintainer-card">
          <h3>Recent generation jobs</h3>
          {jobs.length ? jobs.map((job) => (
            <div className="maintainer-row" key={job.id}>
              <div>
                <strong>{job.status} · {job.currentStage ?? "stage unknown"}</strong>
                <p>{job.errorCode ?? "no code"} {job.errorMessage ?? job.promptSummary}</p>
                <span>{job.creatorEmail ?? job.creatorId ?? "unknown creator"} · {new Date(job.updatedAt).toLocaleString()}</span>
              </div>
              <button type="button" onClick={() => void markJobReviewed(job.id)}>Reviewed</button>
            </div>
          )) : <p>No generation jobs found.</p>}
        </div>
        <div className="maintainer-card">
          <h3>Game metadata</h3>
          {games.length ? games.map((game) => (
            <div className="maintainer-row" key={game.id}>
              <div>
                <strong>{game.title}</strong>
                <p>{game.slug} · {game.publishStatus} · {game.visibility} · plays {game.plays}</p>
                <span>{new Date(game.updatedAt).toLocaleString()}</span>
              </div>
              <div className="maintainer-actions">
                <button type="button" onClick={() => void patchGame(game.id, { publishStatus: "archived" })}>Archive</button>
                <button type="button" onClick={() => void rejectGame(game.id)}>Reject</button>
              </div>
            </div>
          )) : <p>No games found.</p>}
        </div>
        <div className="maintainer-card wide">
          <h3>OSS files</h3>
          {assets.length ? assets.map((asset) => (
            <div className="maintainer-row" key={asset.id}>
              <div>
                <strong>{asset.kind} · {asset.contentType ?? "unknown"}</strong>
                <p>{asset.objectKey}</p>
                <span>{formatBytes(asset.sizeBytes)} · game {asset.gameId ?? "-"} · job {asset.jobId ?? "-"}</span>
              </div>
              <button type="button" onClick={() => void deleteAsset(asset.id)}>Delete</button>
            </div>
          )) : <p>No assets found.</p>}
        </div>
      </div>
    </section>
  );
}

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) {
    return <main className="status-panel">Restoring session...</main>;
  }
  if (!auth.authenticated) {
    return <Navigate to={`/auth/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  return children;
}

function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [error, setError] = React.useState("");
  const next = params.get("next") || "/profile";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await auth.login(email, password);
      navigate(next);
    } catch {
      setError("Unable to sign in with those details.");
    }
  }

  React.useEffect(() => {
    if (params.get("oauth_error") === "google_not_configured") {
      setError("Google login is not configured yet. Use email sign in for now.");
    }
  }, [params]);

  return (
    <AuthShell title="Log in" subtitle="Access your profile and protected Create workspace.">
      <form className="auth-form" onSubmit={submit}>
        <label>
          <span>Email</span>
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
        </label>
        <PasswordField value={password} onChange={setPassword} visible={showPassword} onToggle={() => setShowPassword((value) => !value)} />
        <div className="auth-inline">
          <GoogleLoginLink onUnavailable={setError} />
          <span>还没有注册？<Link to="/auth/register">立即注册</Link></span>
        </div>
        {error && <p className="form-error">{error}</p>}
        <button type="submit">Log in</button>
      </form>
    </AuthShell>
  );
}

function RegisterPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = React.useState("");
  const [displayName, setDisplayName] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [error, setError] = React.useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    try {
      await auth.register(email, password, displayName);
      navigate("/profile");
    } catch {
      setError("Unable to create this account.");
    }
  }

  return (
    <AuthShell title="Create account" subtitle="Register with email, then continue to your profile.">
      <form className="auth-form" onSubmit={submit}>
        <label>
          <span>Email</span>
          <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
        </label>
        <label>
          <span>Display name</span>
          <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
        </label>
        <PasswordField value={password} onChange={setPassword} visible={showPassword} onToggle={() => setShowPassword((value) => !value)} />
        <div className="auth-inline">
          <GoogleLoginLink onUnavailable={setError} />
          <span>已有账号？<Link to="/auth/login">Log in</Link></span>
        </div>
        {error && <p className="form-error">{error}</p>}
        <button type="submit">Register</button>
      </form>
    </AuthShell>
  );
}

function GoogleLoginLink({ onUnavailable }: { onUnavailable: (message: string) => void }) {
  async function startGoogleLogin(event: React.MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    onUnavailable("");
    window.location.href = `${API_BASE_URL}/auth/google/start`;
  }

  return <a href={`${API_BASE_URL}/auth/google/start`} className="google-link" onClick={startGoogleLogin}>Google</a>;
}

function PasswordField({
  value,
  onChange,
  visible,
  onToggle
}: {
  value: string;
  onChange: (value: string) => void;
  visible: boolean;
  onToggle: () => void;
}) {
  return (
    <label>
      <span>Password</span>
      <div className="password-field">
        <input value={value} onChange={(event) => onChange(event.target.value)} type={visible ? "text" : "password"} required minLength={8} />
        <button type="button" onClick={onToggle} aria-label={visible ? "Hide password" : "Show password"}>
          {visible ? <EyeOff size={18} /> : <Eye size={18} />}
        </button>
      </div>
    </label>
  );
}

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <main className="auth-layout">
      <section>
        <p className="eyebrow">Account</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </section>
      {children}
    </main>
  );
}

function AuthCallback() {
  const auth = useAuth();
  const navigate = useNavigate();

  React.useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = hash.get("access_token");
    if (!token) {
      navigate("/auth/login");
      return;
    }
    auth.setTokenAndRefresh(token).then(() => navigate("/profile"));
  }, [auth, navigate]);

  return <EmptyState title="Signing you in" body="Finishing account verification." />;
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <main className="empty-state">
      <h1>{title}</h1>
      <p>{body}</p>
      <Link to="/" className="primary-action">Back home</Link>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <AuthProvider>
      <App />
    </AuthProvider>
  </BrowserRouter>
);
