import React from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, ChevronRight, Clock3, GripVertical, Plus, Sparkles, Play, Settings, Square, Trash2 } from "lucide-react";
import { API_BASE_URL } from "../utils/constants";
import { readApiError } from "../utils/helpers";
import { useAuth } from "../hooks/useAuth";
import { runStageLabel, formatStepMetrics, preparePlayableDocument } from "../utils/helpers";
import { INIT_AGENT_MODES, OPT_AGENT_MODES } from "../types";
import CreationChat from "../components/CreationChat";
import type {
  CreateInputAsset,
  PlanPreviewResponse,
  AIConfigState,
  LLMTestResult,
  AgentMode,
  CreateProject,
  CreateJob,
  CreateRunStep,
  PlanPreview,
  DecentralizedPreviewResponse,
  CreateProjectPreview,
  RecentGame,
  PendingImage,
  CreateRunEvent,
  CreateTaskSummary,
} from "../types";

function isPlanPreview(value: unknown): value is PlanPreview {
  return value !== null && typeof value === "object" && "plan" in value;
}

function isDecentralizedPreview(value: unknown): value is DecentralizedPreviewResponse {
  return value !== null && typeof value === "object" && "candidates" in value;
}

const ACTIVE_STATUSES = new Set(["pending", "generating"]);

function taskStatus(status: string, publishStatus?: string | null) {
  if (publishStatus === "published") return { label: "已发布", tone: "complete" };
  if (status === "completed") return { label: "已完成", tone: "complete" };
  if (status === "planning" || status === "reviewing") return { label: "待确认", tone: "review" };
  if (status === "failed") return { label: "生成失败", tone: "failed" };
  if (status === "canceled" || status === "cancelled") return { label: "已取消", tone: "muted" };
  return { label: status === "pending" ? "排队中" : "生成中", tone: "active" };
}

function taskTitle(prompt: string) {
  const cleaned = prompt.trim().replace(/\s+/g, " ");
  return cleaned.length > 55 ? `${cleaned.slice(0, 55)}…` : cleaned || "未命名游戏";
}

function taskTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "刚刚" : new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function Create() {
  const [message, setMessage] = React.useState("");
  const [status, setStatus] = React.useState("正在检查创作配置...");
  const [aiConfig, setAiConfig] = React.useState<AIConfigState | null>(null);
  const [fundingMode, setFundingMode] = React.useState<"byok" | "voucher">("byok");
  const [vouchers, setVouchers] = React.useState<{ id: string; status: string; expiresAt: string }[]>([]);
  const [voucherId, setVoucherId] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState("https://api.openai.com/v1");
  const [model, setModel] = React.useState("gpt-5.5");
  const [apiKey, setApiKey] = React.useState("");
  const [editingConfig, setEditingConfig] = React.useState(false);
  const [llmTest, setLlmTest] = React.useState<LLMTestResult | null>(null);
  const [agentMode, setAgentMode] = React.useState<AgentMode>("chat");
  const [createType, setCreateType] = React.useState<"init" | "opt">("init");
  const [projectId, setProjectId] = React.useState("");
  const [projects, setProjects] = React.useState<CreateProject[]>([]);
  const [job, setJob] = React.useState<CreateJob | null>(null);
  const [taskHistory, setTaskHistory] = React.useState<CreateTaskSummary[]>([]);
  const [selectedJobId, setSelectedJobId] = React.useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = React.useState(282);
  const [historyError, setHistoryError] = React.useState(false);
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
  const [cancelBusyId, setCancelBusyId] = React.useState<string | null>(null);
  const [pendingImages, setPendingImages] = React.useState<PendingImage[]>([]);
  const streamAbortRef = React.useRef<AbortController | null>(null);
  const selectedJobRef = React.useRef<string | null>(null);
  const composerRef = React.useRef<HTMLFormElement | null>(null);
  const workspaceRef = React.useRef<HTMLDivElement | null>(null);
  const pendingImagesRef = React.useRef<PendingImage[]>([]);
  const { apiFetch, token } = useAuth();
  const optimizableProjects = projects.filter((project) => Boolean(project.gameId) && project.status !== "archived");
  const activeTaskCount = taskHistory.filter((task) => ACTIVE_STATUSES.has(task.status)).length;
  const availableVouchers = vouchers.filter((voucher) => voucher.status === "available" && new Date(voucher.expiresAt).getTime() > Date.now());
  const fundingReady = fundingMode === "voucher" ? Boolean(aiConfig?.officialConfigured && voucherId) : Boolean(aiConfig?.configured && !editingConfig);

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
      const firstReady = projectPayload.find((project) => project.gameId && project.status !== "archived");
      setProjectId((current) => projectPayload.some((project) => project.projectId === current && project.gameId)
        ? current : firstReady?.projectId ?? "");
    }
  }, [apiFetch]);

  const loadTaskHistory = React.useCallback(async () => {
    try {
      const response = await apiFetch("/create/jobs");
      if (!response.ok) throw new Error("Task history unavailable");
      setTaskHistory((await response.json()) as CreateTaskSummary[]);
      setHistoryError(false);
    } catch {
      setHistoryError(true);
    }
  }, [apiFetch]);

  const loadCreateState = React.useCallback(async () => {
    const configResponse = await apiFetch("/create/ai-config");
    if (configResponse.ok) {
      const payload = (await configResponse.json()) as AIConfigState;
      setAiConfig(payload);
      if (payload.baseUrl) setBaseUrl(payload.baseUrl);
      if (payload.model) setModel(payload.model);
      setStatus(payload.configured ? "模型配置已就绪，可以开始创作。" : "请先填写模型配置再开始创作。");
      setEditingConfig(!payload.configured);
    }
    const recentResponse = await apiFetch("/create/recent-game");
    if (recentResponse.ok) {
      setRecentGame((await recentResponse.json()) as RecentGame | null);
    }
    const voucherResponse = await apiFetch("/vouchers/me");
    if (voucherResponse.ok) {
      const list = await voucherResponse.json() as { id: string; status: string; expiresAt: string }[];
      setVouchers(list);
      setVoucherId((current) => list.some((item) => item.id === current && item.status === "available") ? current : list.find((item) => item.status === "available" && new Date(item.expiresAt).getTime() > Date.now())?.id ?? "");
    }
    await loadProjects();
  }, [apiFetch, loadProjects]);

  React.useEffect(() => {
    void loadCreateState();
  }, [loadCreateState]);

  React.useEffect(() => {
    void loadTaskHistory();
    const timer = window.setInterval(() => void loadTaskHistory(), 10000);
    return () => window.clearInterval(timer);
  }, [loadTaskHistory]);

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

  function mergeRunEvent(event: CreateRunEvent, sourceJobId: string) {
    if (selectedJobRef.current !== sourceJobId) return;
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
      setStatus("A generation step completed. Checking task status...");
    } else if (event.outputSummary) {
      setStatus(event.outputSummary);
    }
  }

  async function loadFinalJob(jobId: string): Promise<CreateJob | null> {
    const response = await apiFetch(`/create/jobs/${jobId}`);
    if (response.ok) {
      const payload = (await response.json()) as CreateJob;
      if (selectedJobRef.current === jobId) {
        setJob(payload);
        if (payload.status === "completed") setStatus("游戏已生成，可以预览或发布。");
        else if (payload.status === "failed") setStatus(payload.errorMessage || "游戏生成失败。");
        else if (payload.status === "canceled") setStatus("已终止创作，本次任务不会发布游戏。相关预留资源正在释放。");
      }
      await Promise.all([loadTaskHistory(), loadProjects()]);
      return payload;
    }
    return null;
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
        if (selectedJobRef.current === jobId) setStatus("Run event stream could not be opened. Use Run steps to refresh.");
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split(/\r?\n\r?\n/);
        buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const lines = chunk.split("\n").map((line) => line.replace(/\r$/, ""));
          const eventName = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() ?? "step";
          const dataLine = lines.find((line) => line.startsWith("data:"));
          if (!dataLine) continue;
          const step = JSON.parse(dataLine.slice(5).trim()) as CreateRunStep;
          const event: CreateRunEvent = {
            type: eventName === "done" ? "done" : eventName === "error" ? "error" : "step",
            runId, stepNo: step.stepNo, stage: step.stage, status: step.status,
            outputSummary: step.outputSummary ?? null, createdAt: step.createdAt,
          };
          mergeRunEvent(event, jobId);
          if (event.type === "done") {
            const latest = await loadFinalJob(jobId);
            if (latest && !ACTIVE_STATUSES.has(latest.status)) return;
          }
          if (event.type === "error") {
            await loadFinalJob(jobId);
            return;
          }
        }
      }
      await loadFinalJob(jobId);
    } catch (error) {
      if (!controller.signal.aborted && selectedJobRef.current === jobId) {
        setStatus(error instanceof Error ? error.message : "Run event stream interrupted.");
      }
    } finally {
      if (streamAbortRef.current === controller) setStreaming(false);
    }
  }

  function animateTaskIntoSidebar(from: DOMRect, taskId: string, prompt: string) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      const target = document.getElementById(`create-task-${taskId}`);
      if (!target) return;
      const to = target.getBoundingClientRect();
      const ghost = document.createElement("div");
      ghost.className = "create-task-flight";
      ghost.textContent = taskTitle(prompt);
      Object.assign(ghost.style, {
        left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px`,
      });
      document.body.appendChild(ghost);
      const flight = ghost.animate([
        { transform: "translate(0, 0) scale(1, 1)", opacity: 0.9, borderRadius: "20px" },
        { transform: `translate(${to.left - from.left}px, ${to.top - from.top}px) scale(${to.width / from.width}, ${to.height / from.height})`, opacity: 0.18, borderRadius: "13px" },
      ], { duration: 650, easing: "cubic-bezier(.22,1,.36,1)" });
      flight.onfinish = () => ghost.remove();
      flight.oncancel = () => ghost.remove();
    }));
  }

  function startNewTask(nextProjectId?: string) {
    streamAbortRef.current?.abort();
    selectedJobRef.current = null;
    setSelectedJobId(null);
    setJob(null);
    setRunSteps([]);
    setPlanPreview(null);
    setDecentralizedPreview(null);
    setStreaming(false);
    setStatus("描述你的游戏想法，开始新任务。");
    if (nextProjectId) {
      setCreateType("opt");
      setProjectId(nextProjectId);
      setAgentMode("refine");
      setMessage("");
    } else {
      setCreateType("init");
      setAgentMode("chat");
      setMessage("");
    }
  }

  function focusComposer() {
    window.requestAnimationFrame(() => {
      const textarea = composerRef.current?.querySelector("textarea");
      textarea?.scrollIntoView({ behavior: "smooth", block: "center" });
      textarea?.focus({ preventScroll: true });
    });
  }

  async function openTask(taskId: string) {
    if (selectedJobRef.current === taskId) return;
    streamAbortRef.current?.abort();
    selectedJobRef.current = taskId;
    setSelectedJobId(taskId);
    setJob(null);
    setRunSteps([]);
    setPlanPreview(null);
    setDecentralizedPreview(null);
    setStreaming(false);
    setStatus("正在加载任务详情...");
    try {
      const response = await apiFetch(`/create/jobs/${taskId}`);
      if (!response.ok) throw new Error("任务详情加载失败。");
      const payload = (await response.json()) as CreateJob;
      if (selectedJobRef.current !== taskId) return;
      setJob(payload);
      setStatus(payload.status === "completed" ? "游戏已生成，可以预览或发布。" : payload.status === "failed" ? payload.errorMessage || "游戏生成失败。" : payload.status === "canceled" ? "已终止创作，本次任务不会发布游戏。" : `任务${taskStatus(payload.status).label}。`);
      if (payload.runId) {
        const stepsResponse = await apiFetch(`/create/runs/${payload.runId}/steps`);
        if (stepsResponse.ok && selectedJobRef.current === taskId) setRunSteps((await stepsResponse.json()) as CreateRunStep[]);
        if (payload.status === "planning") await loadPlanPreview(payload.runId);
        if (payload.status === "reviewing") await loadDecentralizedPreviews(payload.runId);
        if (ACTIVE_STATUSES.has(payload.status) && selectedJobRef.current === taskId) void connectRunEvents(payload.runId, payload.id);
      }
    } catch (error) {
      if (selectedJobRef.current === taskId) setStatus(error instanceof Error ? error.message : "任务加载失败。");
    }
  }

  async function deleteTask(item: CreateTaskSummary) {
    if (!window.confirm(`从任务记录中删除「${taskTitle(item.displayTitle || item.prompt)}」及其轨迹？已发布的游戏会保留。`)) return;
    try {
      const response = await apiFetch(`/create/jobs/${encodeURIComponent(item.id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error((await readApiError(response)).message || "删除失败");
      setTaskHistory((current) => current.filter((entry) => entry.id !== item.id));
      if (selectedJobRef.current === item.id) startNewTask();
      void loadProjects();
      setStatus("任务记录和轨迹已从工作区移除。已发布的游戏仍可游玩。");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "删除失败，请稍后重试");
    }
  }

  async function cancelTask(taskId: string) {
    if (!window.confirm("确定终止这个创建任务吗？已生成但尚未发布的内容不会保存为游戏版本。")) return;
    setCancelBusyId(taskId);
    try {
      const response = await apiFetch(`/create/jobs/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error((await readApiError(response)).message || "终止失败");
      setTaskHistory(current => current.map(item => item.id === taskId ? { ...item, status: "canceled" } : item));
      if (selectedJobRef.current === taskId) {
        streamAbortRef.current?.abort();
        setStreaming(false);
        await loadFinalJob(taskId);
        const stepsResponse = await apiFetch(`/create/runs/${encodeURIComponent(taskId)}/steps`);
        if (stepsResponse.ok) setRunSteps(await stepsResponse.json() as CreateRunStep[]);
      }
      setStatus("已终止创作，本次任务不会发布游戏。");
    } catch (error) { setStatus(error instanceof Error ? error.message : "终止失败，请稍后重试"); }
    finally { setCancelBusyId(null); }
  }

  function beginResize(event: React.PointerEvent<HTMLDivElement>) {
    if (window.innerWidth <= 800) return;
    event.preventDefault();
    const move = (next: PointerEvent) => {
      const left = workspaceRef.current?.getBoundingClientRect().left ?? 0;
      setSidebarWidth(Math.max(228, Math.min(420, next.clientX - left)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.classList.remove("resizing-create-sidebar");
    };
    document.body.classList.add("resizing-create-sidebar");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop, { once: true });
  }

  function addImages(files: FileList | null) {
    if (!files?.length) return;
    const accepted = Array.from(files).filter((file) => ["image/png", "image/jpeg", "image/webp"].includes(file.type));
    if (accepted.length === 0) {
      setStatus("Attach PNG, JPEG, or WebP images.");
      return;
    }
    if (pendingImagesRef.current.length + accepted.length > 3) {
      setStatus("At most three reference images are supported.");
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

  async function cleanup已上传Images(inputAssets: CreateInputAsset[]) {
    if (inputAssets.length === 0) return;
    await Promise.allSettled(inputAssets.map((asset) => apiFetch(`/uploads/${asset.assetId}`, { method: "DELETE" })));
    setPendingImages((current) => current.map((image) => ({ ...image, uploaded: undefined })));
  }

  async function submitJob(event: React.FormEvent) {
    event.preventDefault();
    if (agentMode === "chat") return;
    const startingRect = composerRef.current?.getBoundingClientRect();
    const submittedPrompt = message;
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
    setStatus("Starting Create run...");
    try {
    inputAssets = await uploadPendingImages();
    const response = await apiFetch("/create/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        prompt: message,
        files: [],
        inputAssets,
        agentMode: requestAgentMode,
        createType,
        projectId: createType === "opt" ? projectId : undefined,
        fundingMode,
        voucherId: fundingMode === "voucher" ? voucherId : undefined
      })
    });
    if (!response.ok) {
      const error = await readApiError(response);
      await cleanup已上传Images(inputAssets);
      if (error.detail && typeof error.detail === "object" && (error.detail as Record<string, unknown>).code === "LLM_CONFIG_INVALID" && (error.detail as Record<string, unknown>).llm) {
        setLlmTest((error.detail as Record<string, unknown>).llm as LLMTestResult);
        setEditingConfig(true);
        setStatus(error.message);
      } else if (response.status === 401) {
        setStatus("Please log in again before creating a game.");
      } else {
        setStatus(error.message);
      }
      return;
    }
    const payload = (await response.json()) as CreateJob;
    selectedJobRef.current = payload.id;
    setSelectedJobId(payload.id);
    setJob(payload);
    setTaskHistory((current) => [{
      id: payload.id, prompt: submittedPrompt, status: payload.status,
      agentMode: payload.agentMode, createType: payload.createType,
      projectId: payload.projectId, createdAt: payload.createdAt,
    }, ...current.filter((item) => item.id !== payload.id)]);
    if (payload.projectId) setProjectId(payload.projectId);
    setStatus("Task started. Generation progress is updating below.");
    if (startingRect) animateTaskIntoSidebar(startingRect, payload.id, submittedPrompt);
    void loadTaskHistory();
    if (payload.runId) {
      void connectRunEvents(payload.runId, payload.id);
    }
    } catch (error) {
      await cleanup已上传Images(inputAssets);
      setStatus(error instanceof Error ? error.message : "Could not start the task. Please try again.");
    } finally {
      setBusy(false);
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
    startNewTask(nextProjectId);
    setStatus("继续优化 selected. Add the next request for this project.");
    void loadProjectPreview(nextProjectId);
    focusComposer();
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
      <header className="create-page-heading">
        <div>
          <p className="eyebrow">游戏工作室 / 创建</p>
          <h1>让灵感成为游戏。</h1>
          <p>可以同时创建多个不同的游戏。任务分别运行，进度会保留在左侧列表。</p>
        </div>
        <span className="create-page-mark"><Sparkles size={17} /> 创作空间</span>
      </header>
      <div className="create-workspace" ref={workspaceRef} style={{ "--task-sidebar-width": `${sidebarWidth}px` } as React.CSSProperties}>
        <aside className="create-sidebar" aria-label="创建任务">
          <div className="create-sidebar-top">
            <div><span className="create-overline">我的工作区</span><h2>任务记录 <small>{taskHistory.length}</small></h2>{activeTaskCount > 0 && <span className="create-overline">{activeTaskCount} 个任务正在排队或生成</span>}</div>
            <button type="button" className="create-new-icon" onClick={() => startNewTask()} aria-label="新建任务"><Plus size={19} /></button>
          </div>
          <button type="button" className={`create-new-task ${selectedJobId === null ? "selected" : ""}`} onClick={() => startNewTask()}>
            <span className="create-new-task-symbol"><Plus size={17} /></span><span>新建游戏<strong>从一个想法开始</strong></span><ChevronRight size={15} />
          </button>
          <div className="create-sidebar-label"><span>最近任务</span><span>{taskHistory.length > 0 ? "按时间排序" : ""}</span></div>
          <div className="create-task-list">
            {taskHistory.length === 0 && <p className="create-task-empty">{historyError ? "任务记录暂时无法加载，请刷新页面。" : "开始创建后，你的游戏任务会显示在这里。"}</p>}
            {taskHistory.map((item) => {
              const state = taskStatus(item.status);
              return <div id={`create-task-${item.id}`} key={item.id} className={`create-task-row ${selectedJobId === item.id ? "selected" : ""}`}>
                <button type="button" className="create-task-item" onClick={() => void openTask(item.id)} aria-current={selectedJobId === item.id ? "true" : undefined}>
                <span className="create-task-item-top"><span className={`create-task-dot ${state.tone}`} /><span className={`create-task-state ${state.tone}`}>{state.label}</span><time>{taskTime(item.createdAt)}</time></span>
                <strong>{taskTitle(item.displayTitle || item.prompt)}</strong>
                <span className="create-task-item-foot">{item.createType === "opt" ? "继续优化" : "新建游戏"} <span>·</span> {({ chat: "对话", react: "推理行动", plan: "规划", decentralized: "多智能体", refine: "精修" } as Record<string, string>)[item.agentMode ?? ""] ?? "创作"}</span>
                </button>
                {["pending", "generating", "planning", "reviewing"].includes(item.status)
                  ? <button type="button" className="create-task-cancel" disabled={cancelBusyId === item.id} aria-label={`终止任务：${taskTitle(item.displayTitle || item.prompt)}`} title="终止创建" onClick={() => void cancelTask(item.id)}><Square size={13} fill="currentColor" /></button>
                  : <button type="button" className="create-task-delete" aria-label={`删除任务：${taskTitle(item.displayTitle || item.prompt)}`} title="删除任务和轨迹" onClick={() => void deleteTask(item)}><Trash2 size={15} /></button>}
              </div>;
            })}
          </div>
          <div className="create-sidebar-foot"><span className="create-sidebar-spark">✦</span> 每个想法都值得被认真创造。</div>
        </aside>
        <div className="create-resize-handle" role="separator" aria-label="Resize task list" aria-orientation="vertical" aria-valuemin={228} aria-valuemax={420} aria-valuenow={sidebarWidth} tabIndex={0} onPointerDown={beginResize} onKeyDown={(event) => {
          if (event.key === "ArrowLeft") { event.preventDefault(); setSidebarWidth((width) => Math.max(228, width - 20)); }
          if (event.key === "ArrowRight") { event.preventDefault(); setSidebarWidth((width) => Math.min(420, width + 20)); }
        }}><GripVertical size={17} /></div>
        <div className="create-detail">
      {selectedJobId ? (
        <section className="create-focus-card" aria-live="polite">
          <div className="create-focus-top"><span className="create-overline">任务工作区</span><button type="button" onClick={() => startNewTask()}><ArrowLeft size={15} /> 新建任务</button></div>
          <div className="create-focus-main">
            <div className="create-focus-symbol"><Sparkles size={28} /></div>
            <div className="create-focus-copy"><span>游戏创作</span><h2>{taskTitle(job?.displayTitle ?? taskHistory.find((item) => item.id === selectedJobId)?.displayTitle ?? job?.prompt ?? "加载任务中...")}</h2><p><Clock3 size={14} /> {taskTime(job?.createdAt ?? taskHistory.find((item) => item.id === selectedJobId)?.createdAt ?? "")}</p></div>
            <span className={`create-focus-status ${taskStatus(job?.status ?? taskHistory.find((item) => item.id === selectedJobId)?.status ?? "pending", job?.publishStatus).tone}`}><span />{taskStatus(job?.status ?? taskHistory.find((item) => item.id === selectedJobId)?.status ?? "pending", job?.publishStatus).label}</span>
          </div>
          <div className="create-progress-track" aria-hidden="true"><span className="done" /><span className={runSteps.length > 0 ? "done" : ""} /><span className={job?.status === "completed" ? "done" : ""} /><span className={job?.publishStatus === "published" ? "done" : ""} /></div>
          <div className="create-progress-labels"><span>等待</span><span>生成</span><span>完成</span><span>发布</span></div>
          {job && ["pending", "generating", "planning", "reviewing"].includes(job.status) && <div className="create-cancel-strip"><span>此任务会独立运行。现在就能并行创建另一款游戏；同一游戏的优化仍需等待当前任务结束。</span><button type="button" className="create-parallel-action" onClick={() => { startNewTask(); focusComposer(); }}><Plus size={13} /> 并行新建游戏</button><button type="button" disabled={cancelBusyId === job.id} onClick={() => void cancelTask(job.id)}><Square size={13} fill="currentColor" /> {cancelBusyId === job.id ? "正在终止…" : "终止创建"}</button></div>}
          {job?.prompt && <details className="create-prompt-details"><summary>查看完整创作要求</summary><p>{job.prompt}</p></details>}
        </section>
      ) : <div className="create-compose-heading"><span className="create-overline">开始创作</span><h2>描述你想玩的游戏</h2><p>通过 Chat 一起完善想法，确认画像后交给 ReAct；也可以选择其他创作方式。</p></div>}
      {!selectedJobId && <>
      {aiConfig && (!aiConfig.configured || editingConfig) && (
        <form className="prompt-panel" onSubmit={saveConfig}>
          <label>
            <span>模型接口地址</span>
            <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} required />
          </label>
          <label>
            <span>模型名称</span>
            <input value={model} onChange={(event) => setModel(event.target.value)} required />
          </label>
          <label>
            <span>API 密钥</span>
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
                  setStatus("模型配置已就绪，可以开始创作。");
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
          <span>模型配置已保存，密钥由后端安全保管。</span>
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
            修改配置
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
            <span>最近创作</span>
            <strong>{recentGame.title}</strong>
          </div>
          <Link to={recentGame.playUrl} className="secondary-action">开始游玩</Link>
        </section>
      )}
      <form className="prompt-panel" onSubmit={submitJob} ref={composerRef}>
        <fieldset className="create-mode-picker"><legend>生成费用来源</legend><div className="create-mode-options">
          <button type="button" className={fundingMode === "byok" ? "selected" : undefined} onClick={() => setFundingMode("byok")}>使用我的 API Key</button>
          <button type="button" className={fundingMode === "voucher" ? "selected" : undefined} onClick={() => setFundingMode("voucher")}>使用官方生成券</button>
        </div></fieldset>
        {fundingMode === "voucher" && <label><span>选择生成券</span><select value={voucherId} onChange={(event) => setVoucherId(event.target.value)} disabled={!availableVouchers.length}>
          {availableVouchers.length ? availableVouchers.map((voucher) => <option key={voucher.id} value={voucher.id}>有效期至 {new Date(voucher.expiresAt).toLocaleDateString()} · {voucher.id.slice(0, 8)}</option>) : <option value="">暂无可用券</option>}
        </select><small>{aiConfig?.officialConfigured ? "一张券支付一次创建或优化任务。失败时自动返还。" : "官方模型暂未配置，请联系管理员。"} <Link to="/rewards">查看券包与活动</Link></small></label>}
        <div className="create-type-row">
          <button
            type="button"
            className={createType === "init" ? "selected" : undefined}
            onClick={() => {
              setCreateType("init");
              if (!INIT_AGENT_MODES.includes(agentMode as (typeof INIT_AGENT_MODES)[number])) setAgentMode("chat");
              setProjectPreview(null);
            }}
          >
            新建游戏
          </button>
          <button
            type="button"
            className={createType === "opt" ? "selected" : undefined}
            onClick={() => {
              setCreateType("opt");
              if (projectId) void loadProjectPreview(projectId);
              focusComposer();
            }}
            disabled={optimizableProjects.length === 0}
          >
            继续优化
          </button>
        </div>
        {createType === "opt" && (
          <label>
            <span>选择要优化的游戏</span>
            <select
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                void loadProjectPreview(event.target.value);
              }}
              required
            >
              {optimizableProjects.map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {taskTitle(project.title)} · {project.publishStatus === "published" ? "已发布" : "草稿"}{project.currentVersionNo ? ` · 第 ${project.currentVersionNo} 版` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
        {createType === "opt" && (
          <section className="refine-preview-panel">
            <div className="plan-review-header">
              <div>
                <span>当前版本预览</span>
                <strong>{projectPreview ? `${projectPreview.title} · v${projectPreview.versionNo}` : "请选择已有游戏"}</strong>
              </div>
              <button type="button" className="inline-action" disabled={previewBusy || !projectId} onClick={() => void loadProjectPreview(projectId)}>
                {previewBusy ? "加载中..." : "刷新预览"}
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
              <p className="muted-copy">先创建并保存游戏，再基于最新版本继续优化。</p>
            )}
            <small>这里可以试玩尚未发布的版本。使用键盘前请先点击游戏画面。</small>
          </section>
        )}
        <fieldset className="create-mode-picker">
          <legend>创作模式</legend>
          <div className="create-mode-options">
            {(createType === "opt" ? OPT_AGENT_MODES : INIT_AGENT_MODES).map((mode) => (
              <button key={mode} type="button" className={agentMode === mode ? "selected" : undefined}
                aria-pressed={agentMode === mode} onClick={() => setAgentMode(mode)}>{({ chat: "Chat · 完善想法", react: "ReAct · 直接生成", plan: "规划", decentralized: "多智能体", refine: "精修" } as Record<string, string>)[mode] ?? mode}</button>
            ))}
          </div>
        </fieldset>
        {agentMode !== "chat" && <div className="multimodal-composer">
          {pendingImages.length > 0 && (
            <div className="image-preview-list">
              {pendingImages.map((image) => (
                <div className="image-preview" key={image.id}>
                  <img src={image.previewUrl} alt={image.file.name} />
                  <button type="button" onClick={() => removeImage(image.id)} disabled={busy || streaming}>
                    移除
                  </button>
                  {image.uploaded && <span>已上传</span>}
                </div>
              ))}
            </div>
          )}
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="例如：制作一款通过连接星座解谜的霓虹风格游戏..."
            maxLength={4000}
            required
            disabled={!fundingReady || busy}
          />
          <label className="create-image-attach">参考图片（最多 3 张）<input type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={(event) => { addImages(event.target.files); event.target.value = ""; }} disabled={busy || streaming || pendingImages.length >= 3} /></label>
          <div className="composer-actions">
            <button type="submit" disabled={!message.trim() || !fundingReady || busy || streaming}>
              {streaming ? "生成中..." : "创建游戏"}
            </button>
          </div>
        </div>}
      </form>
      {agentMode === "chat" && <CreationChat createType={createType} projectId={projectId} fundingMode={fundingMode} voucherId={voucherId} fundingReady={fundingReady}
        onCreated={(payload) => {
          selectedJobRef.current = payload.id;
          setSelectedJobId(payload.id); setJob(payload); setRunSteps([]); setPlanPreview(null); setDecentralizedPreview(null);
          setStatus("画像已确认，ReAct 正在创建游戏。进度会显示在任务记录中。");
          void loadTaskHistory();
          if (payload.runId) void connectRunEvents(payload.runId, payload.id);
        }} />}
      </>}
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
            刷新预览s
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
          <div className="create-result-summary">
              {job.status === "completed" && job.coverDataUrl && <img className="create-result-cover" src={job.coverDataUrl} alt={`Cover for ${taskTitle(job.prompt)}`} />}
              <span>CREATION STATUS</span>
              <strong>{job.publishStatus === "published" ? "游戏已发布" : job.status === "completed" ? "游戏已生成" : job.status === "failed" ? "本次生成失败" : job.status === "canceled" ? "创作已终止" : job.status === "planning" || job.status === "reviewing" ? "等待你的确认" : "正在创作游戏"}</strong>
              <p>{job.status === "canceled" ? "任务轨迹已保留，未完成的游戏版本不会发布。" : streaming ? "正在接收实时进度。" : job.status === "completed" ? "可以预览、发布或继续优化。" : job.status === "failed" ? "查看任务轨迹了解原因。" : "你可以切换任务，稍后回来查看进度。"}</p>
              <details className="create-technical-details">
                <summary>Technical details</summary>
                <span>Task: {job.id}</span>
                {job.projectId && <span>Project: {job.projectId}</span>}
                {job.runId && <span>Run: {job.runId}</span>}
                {job.versionNo && <span>Version: v{job.versionNo}</span>}
                <span>Mode: {job.agentMode ?? agentMode}</span>
              </details>
            </div>
            <div className="result-actions">
              {job.runId && <button type="button" className="secondary-action" disabled={busy} onClick={loadRunSteps}>Run steps</button>}
              {job.status === "completed" && <button type="button" className="secondary-action" disabled={busy} onClick={continueCurrentProject}>继续优化</button>}
              {job.status === "completed" && job.publishStatus === "draft" && <button type="button" className="primary-action" disabled={busy} onClick={() => void publishDraft()}>Publish</button>}
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
                const metrics = step.metrics ?? {};
                const outputTokens = metrics.tokenUsage && typeof metrics.tokenUsage === "object"
                  ? (metrics.tokenUsage as Record<string, unknown>).outputTokens
                  : metrics.outputTokens;
                return (
                  <div key={step.stepNo}>
                    <span>第 {step.stepNo} 步 · {runStageLabel(step.stage)} · {taskStatus(step.status).label}</span>
                    {step.inputSummary && <p>{step.inputSummary}</p>}
                    {(step.stage === "llm_call" || step.stage === "cover_llm_call") && (
                      <small>
                        prefix words {String(metrics.prefixEnglishWords ?? "-")} · 中文 {String(metrics.prefixChineseChars ?? "-")} · output tokens {String(outputTokens ?? "-")}
                      </small>
                    )}
                    {step.stage === "cover_uploaded" && (
                      <small>
                        {String(metrics.contentType ?? "-")} · {String(metrics.sizeBytes ?? "-")} bytes · {String(metrics.objectKey ?? "-")}
                      </small>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}
        </div>
      </div>
    </main>
  );
}


export default Create;
