import React from "react";
import { Link } from "react-router-dom";
import { Play, Settings } from "lucide-react";
import { API_BASE_URL } from "../utils/constants";
import { readApiError } from "../utils/helpers";
import { useAuth } from "../hooks/useAuth";
import { runStageLabel, formatStepMetrics, preparePlayableDocument } from "../utils/helpers";
import { INIT_AGENT_MODES, OPT_AGENT_MODES } from "../types";
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
} from "../types";

function isPlanPreview(value: unknown): value is PlanPreview {
  return value !== null && typeof value === "object" && "plan" in value;
}

function isDecentralizedPreview(value: unknown): value is DecentralizedPreviewResponse {
  return value !== null && typeof value === "object" && "experts" in value;
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
      } else if (error.detail && typeof error.detail === "object" && (error.detail as Record<string, unknown>).code === "LLM_CONFIG_INVALID" && (error.detail as Record<string, unknown>).llm) {
        setLlmTest((error.detail as Record<string, unknown>).llm as LLMTestResult);
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


export default Create;
