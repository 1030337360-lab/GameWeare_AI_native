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
import { Eye, EyeOff, Gamepad2, LogOut, Play, Plus, Settings, UserRound } from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8080";
const TOKEN_STORAGE_KEY = "yahaha_access_token";
const AGENT_MODES = ["chat", "react", "plan", "init", "opt"] as const;

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
  section: string;
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
  agentMode: AgentMode | null;
  createType: "init" | "opt" | null;
  projectId: string | null;
  runId: string | null;
  taskId: string | null;
  resumeStatus: string | null;
};

type AIConfigState = {
  authenticated: boolean;
  configured: boolean;
  baseUrl: string | null;
  model: string | null;
  provider: string | null;
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
  latestRunId: string | null;
  latestRunStatus: string | null;
  createdAt: string;
  updatedAt: string;
};

type AuthContextValue = SessionState & {
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

  const apiFetch = React.useCallback(
    (path: string, init: RequestInit = {}) => {
      const headers = new Headers(init.headers);
      if (token) headers.set("Authorization", `Bearer ${token}`);
      return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
    },
    [token]
  );

  const loadSession = React.useCallback(async (nextToken = token) => {
    if (!nextToken) {
      setSession({ authenticated: false, user: null });
      return;
    }
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
    setSession({ authenticated: false, user: null });
  }, [apiFetch, token]);

  const setTokenAndRefresh = React.useCallback(async (nextToken: string) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, nextToken);
    setToken(nextToken);
    await loadSession(nextToken);
  }, [loadSession]);

  const value = React.useMemo(
    () => ({ ...session, token, apiFetch, login, register, logout, setTokenAndRefresh }),
    [apiFetch, login, logout, register, session, setTokenAndRefresh, token]
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
  const { token } = useAuth();

  React.useEffect(() => {
    fetchJson<Game[]>("/games", fallbackGames, token).then(setGames);
  }, [token]);

  return (
    <div className="app-shell">
      <Header />
      <Routes>
        <Route path="/" element={<Home games={games} />} />
        <Route path="/create" element={<ProtectedRoute><Create /></ProtectedRoute>} />
        <Route path="/games/:gameId" element={<GameDetail games={games} />} />
        <Route path="/play/:gameId" element={<PlayGame games={games} />} />
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
    </header>
  );
}

function Home({ games }: { games: Game[] }) {
  const auth = useAuth();
  const sections = ["Players' Choice", "Trending", "Recommended For You", "Recently Created"];

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">AI native arcade</p>
          <h1>Play community games. Generate the next one.</h1>
          <p>Browse playable HTML5 game manifests now; the Create pipeline is stubbed but its API shape is preserved.</p>
        </div>
        <Link to={auth.authenticated ? "/create" : "/auth/login?next=/create"} className="hero-action">
          <Plus size={20} />
          Start creating
        </Link>
      </section>
      {sections.map((section) => {
        const sectionGames = games.filter((game) => game.section === section);
        if (sectionGames.length === 0) return null;
        return <GameSection key={section} title={section} games={sectionGames} />;
      })}
    </main>
  );
}

function GameSection({ title, games }: { title: string; games: Game[] }) {
  return (
    <section className="game-section">
      <h2>{title}</h2>
      <div className="game-grid">
        {games.map((game) => (
          <article className="game-card" key={game.id}>
            <Link to={`/games/${game.id}`} className="cover-link">
              <img src={game.coverUrl} alt="" />
              <span className="play-count">{formatPlays(game.plays)}</span>
            </Link>
            <div className="card-body">
              <div>
                <h3>{game.title}</h3>
                <p>by {game.author}</p>
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
          </article>
        ))}
      </div>
    </section>
  );
}

function GameDetail({ games }: { games: Game[] }) {
  const { gameId } = useParams();
  const [remoteGame, setRemoteGame] = React.useState<Game | null>(null);
  const game = games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId) ?? remoteGame;

  React.useEffect(() => {
    if (!gameId || games.some((item) => item.id === gameId) || fallbackGames.some((item) => item.id === gameId)) return;
    fetchJson<Game | null>(`/games/${gameId}`, null).then(setRemoteGame);
  }, [gameId, games]);

  if (!game) return <EmptyState title="Game not found" body="The selected game id is not in the local catalog." />;

  return (
    <main className="detail-layout">
      <img src={game.coverUrl} alt="" className="detail-cover" />
      <section className="detail-copy">
        <p className="eyebrow">{game.section}</p>
        <h1>{game.title}</h1>
        <p>{game.description}</p>
        <div className="meta-grid">
          <span>Author: {game.author}</span>
          <span>Plays: {formatPlays(game.plays)}</span>
          <span>Published: {new Date(game.publishedAt).toLocaleDateString()}</span>
        </div>
        <div className="tag-row">
          {game.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <Link to={`/play/${game.id}`} className="primary-action">
          <Play size={18} />
          Play now
        </Link>
      </section>
    </main>
  );
}

function PlayGame({ games }: { games: Game[] }) {
  const { gameId } = useParams();
  const [remoteGame, setRemoteGame] = React.useState<Game | null>(null);
  const game = games.find((item) => item.id === gameId) ?? fallbackGames.find((item) => item.id === gameId) ?? remoteGame;
  const [manifest, setManifest] = React.useState<Manifest | null>(null);
  const [srcDoc, setSrcDoc] = React.useState("");
  const [loadError, setLoadError] = React.useState("");
  const frameRef = React.useRef<HTMLIFrameElement | null>(null);
  const { apiFetch, token } = useAuth();

  function prepareGameDocument(html: string) {
    return html
      .replace(/cursor\s*:\s*[^;}"']+;?/gi, "")
      .replace(/if\s*\([^)]*requestPointerLock[^)]*\)\s*[^;{}]*requestPointerLock\([^)]*\);?/gi, "")
      .replace(/[^;\n{}]*requestPointerLock\([^)]*\);?/gi, "");
  }

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
        setSrcDoc(prepareGameDocument(await response.text()));
      } catch {
        setLoadError("The playable document could not be loaded.");
        void apiFetch("/events/play", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ gameId, event: "game_load_error" })
        }).catch(() => undefined);
      }
    });
  }, [apiFetch, gameId, token]);

  React.useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const data = event.data as { source?: string; type?: string; gameId?: string; payload?: Record<string, unknown> };
      if (!gameId || data?.source !== "yahaha-game" || data.gameId !== gameId) return;
      if (!["game_start", "game_end", "game_load_error"].includes(data.type ?? "")) return;
      void apiFetch("/events/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          gameId,
          event: data.type,
          metadata: data.payload ?? {}
        })
      }).catch(() => undefined);
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [apiFetch, gameId]);

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
          <p className="eyebrow">Sandbox Play</p>
          <h1>{game.title}</h1>
        </div>
        <Link to={`/games/${game.id}`} className="secondary-action">Details</Link>
      </section>
      <iframe
        ref={frameRef}
        className="game-frame"
        title={game.title}
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        tabIndex={0}
      />
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
  const [recentGame, setRecentGame] = React.useState<RecentGame | null>(null);
  const [busy, setBusy] = React.useState(false);
  const { apiFetch } = useAuth();

  const loadCreateState = React.useCallback(async () => {
    const configResponse = await apiFetch("/create/ai-config");
    if (configResponse.ok) {
      const payload = (await configResponse.json()) as AIConfigState;
      setAiConfig(payload);
      if (payload.baseUrl) setBaseUrl(payload.baseUrl);
      if (payload.model) setModel(payload.model);
      setStatus(payload.configured ? "AI configuration is ready. Static test generation is enabled." : "Add your AI configuration before creating.");
      setEditingConfig(!payload.configured);
    }
    const recentResponse = await apiFetch("/create/recent-game");
    if (recentResponse.ok) {
      setRecentGame((await recentResponse.json()) as RecentGame | null);
    }
    const projectsResponse = await apiFetch("/create/projects");
    if (projectsResponse.ok) {
      const projectPayload = (await projectsResponse.json()) as CreateProject[];
      setProjects(projectPayload);
      if (!projectId && projectPayload.length > 0) setProjectId(projectPayload[0].projectId);
    }
  }, [apiFetch, projectId]);

  React.useEffect(() => {
    void loadCreateState();
  }, [loadCreateState]);

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
      setStatus("AI configuration saved. You can create a static test game now.");
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
        body: JSON.stringify({ baseUrl, model, apiKey })
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

  async function submitJob(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setLlmTest(null);
    setStatus("Generating static test game...");
    setJob(null);
    if (createType === "opt" && !projectId) {
      setStatus("Select a project before continuing optimization.");
      setBusy(false);
      return;
    }
    const response = await apiFetch("/create/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: message, files: [], agentMode, createType, projectId: createType === "opt" ? projectId : undefined })
    });
    if (!response.ok) {
      const error = await readApiError(response);
      if (response.status === 409) {
        setStatus("AI configuration is required before creating.");
        setAiConfig({ authenticated: true, configured: false, baseUrl, model, provider: "fighting" });
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
    setStatus(`Job ${payload.id} completed. Project ${payload.projectId ?? "created"} is ready to continue.`);
    await loadCreateState();
    setBusy(false);
  }

  return (
    <main className="create-layout">
      <section>
        <p className="eyebrow">Create</p>
        <h1>Describe a game idea</h1>
        <p>Configure base_url, model, and api_key once. The backend calls the OpenAI Responses API format and keeps the multi-agent pipeline reserved behind this API shape.</p>
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
            <button type="button" disabled={busy || !apiKey.trim()} onClick={testConfig}>Test settings</button>
            <button type="submit" disabled={busy}>Save AI config</button>
            {aiConfig.configured && (
              <button
                type="button"
                className="ghost-button"
                disabled={busy}
                onClick={() => {
                  setEditingConfig(false);
                  setApiKey("");
                  setLlmTest(null);
                  setStatus("AI configuration is ready. Static test generation is enabled.");
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
          <span>AI config ready: {aiConfig.provider} · {aiConfig.model} · {aiConfig.baseUrl}</span>
          <button
            type="button"
            className="inline-action"
            onClick={() => {
              setEditingConfig(true);
              setLlmTest(null);
              setStatus("Update base_url, model, and api_key, then save the new configuration.");
            }}
          >
            <Settings size={16} />
            Reconfigure
          </button>
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
            onClick={() => setCreateType("init")}
          >
            Initial create
          </button>
          <button
            type="button"
            className={createType === "opt" ? "selected" : undefined}
            onClick={() => setCreateType("opt")}
            disabled={projects.length === 0}
          >
            Continue optimize
          </button>
        </div>
        {createType === "opt" && (
          <label>
            <span>project_id</span>
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)} required>
              {projects.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.title} · {project.projectId}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="mode-picker">
          <button type="button" className="mode-toggle" onClick={() => setModeOpen((value) => !value)}>
            Mode: {agentMode}
          </button>
          {modeOpen && (
            <div className="mode-options">
              {AGENT_MODES.map((mode) => (
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
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="A neon puzzle game where players connect constellations..."
          disabled={!aiConfig?.configured || editingConfig || busy}
        />
        <button type="submit" disabled={!aiConfig?.configured || editingConfig || busy}>Create game</button>
      </form>
      <div className="status-panel">{status}</div>
      {job && (
        <section className="job-panel">
          <div className="result-panel">
            <div>
              <span>Generated game</span>
              <strong>{job.gameSlug ?? job.id}</strong>
              {job.projectId && <span>Project: {job.projectId}</span>}
              {job.runId && <span>Run: {job.runId}</span>}
              {job.taskId && <span>Task: {job.taskId}</span>}
              <span>Mode: {job.agentMode ?? agentMode}</span>
            </div>
            {job.playUrl && <Link to={job.playUrl} className="primary-action"><Play size={18} />Play now</Link>}
          </div>
          <div className="log-list">
            {job.logs.map((log) => (
              <div key={`${log.stage}-${log.message}`}>
                <span>{log.stage} · {log.status}</span>
                <p>{log.message}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function Profile() {
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth.user;

  if (!user) return null;

  async function handleLogout() {
    await auth.logout();
    navigate("/auth/login");
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
      <button type="button" className="secondary-action logout-action" onClick={handleLogout}>
        <LogOut size={18} />
        Log out
      </button>
    </main>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  const location = useLocation();
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
