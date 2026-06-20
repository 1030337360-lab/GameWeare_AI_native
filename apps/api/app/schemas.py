from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


class Game(BaseModel):
    id: str
    title: str
    author: str
    description: str
    tags: list[str]
    publishedAt: datetime
    coverUrl: str
    plays: int
    likes: int = 0
    favorites: int = 0
    likedByMe: bool = False
    favoritedByMe: bool = False
    section: str


class GameManifest(BaseModel):
    id: str
    title: str
    version: str = "1.0.0"
    entry: str = "index.html"
    bundleUrl: str
    documentUrl: str | None = None
    assets: list[str] = Field(default_factory=list)
    runtime: str = "iframe-html5"
    sandbox: list[str] = Field(default_factory=lambda: ["allow-scripts"])


class UserProfile(BaseModel):
    id: str
    email: str | None = None
    displayName: str
    avatarUrl: str | None = None
    role: str
    lastLoginAt: datetime | None = None


class SessionState(BaseModel):
    authenticated: bool = False
    user: UserProfile | None = None


class AuthResponse(SessionState):
    accessToken: str | None = None
    tokenType: str = "bearer"
    expiresIn: int | None = None


class RegisterRequest(BaseModel):
    email: str
    password: str
    displayName: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class CreateInputAsset(BaseModel):
    assetId: str
    objectKey: str
    publicUrl: str | None = None
    contentType: str
    filename: str | None = None
    size: int


class CreateJobRequest(BaseModel):
    prompt: str = ""
    files: list[str] = Field(default_factory=list)
    inputAssets: list[CreateInputAsset] = Field(default_factory=list)
    agentMode: Literal["chat", "react", "plan", "refine", "decentralized", "init", "opt"] = "chat"
    createType: Literal["init", "opt"] = "init"
    projectId: str | None = None


class AIConfigRequest(BaseModel):
    baseUrl: str
    model: str
    apiKey: str
    provider: str = "fighting"


class AIConfigTestRequest(BaseModel):
    baseUrl: str | None = None
    model: str | None = None
    apiKey: str | None = None
    provider: str = "fighting"


class AIConfigState(BaseModel):
    authenticated: bool = False
    configured: bool = False
    baseUrl: str | None = None
    model: str | None = None
    provider: str | None = None
    staticGeneration: bool = False


class LLMTestResult(BaseModel):
    ok: bool
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentLog(BaseModel):
    stage: str
    status: Literal["pending", "running", "succeeded", "failed", "skipped", "completed"]
    message: str


class RecentGame(BaseModel):
    gameId: str
    gameSlug: str
    title: str
    playUrl: str
    jobId: str


class CreateJob(BaseModel):
    id: str
    status: Literal[
        "pending",
        "planning",
        "generating",
        "building",
        "reviewing",
        "uploading",
        "completed",
        "failed",
        "canceled",
        "stubbed",
    ]
    prompt: str
    createdAt: datetime
    logs: list[AgentLog]
    gameId: str | None = None
    gameSlug: str | None = None
    playUrl: str | None = None
    manifestUrl: str | None = None
    publishStatus: str | None = None
    visibility: str | None = None
    versionNo: int | None = None
    agentMode: str | None = None
    createType: str | None = None
    projectId: str | None = None
    runId: str | None = None
    taskId: str | None = None
    resumeStatus: str | None = None


class CreateProject(BaseModel):
    projectId: str
    title: str
    status: str
    gameId: str | None = None
    gameSlug: str | None = None
    publishStatus: str | None = None
    visibility: str | None = None
    currentVersionNo: int | None = None
    latestRunId: str | None = None
    latestRunStatus: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
    updatedAt: datetime


class CreateProjectPreview(BaseModel):
    projectId: str
    gameId: str
    gameSlug: str
    title: str
    description: str | None = None
    versionId: str
    versionNo: int
    entryFile: str
    html: str
    source: dict[str, Any] = Field(default_factory=dict)


class CreateProjectDeleteResult(BaseModel):
    projectId: str
    gameId: str | None = None
    gameSlug: str | None = None
    deleted: bool
    runLogsPreserved: bool = True


class CreateRun(BaseModel):
    runId: str
    taskId: str
    projectId: str
    createType: str
    agentMode: str
    status: str
    summary: dict[str, Any] = Field(default_factory=dict)
    logObjectKey: str
    jobId: str | None = None
    gameId: str | None = None
    versionId: str | None = None
    startedAt: datetime
    completedAt: datetime | None = None


class CreateRunStep(BaseModel):
    stepNo: int
    stage: str
    status: str
    inputSummary: str | None = None
    outputSummary: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime


class PlanDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected"]


class PlanPreviewResponse(BaseModel):
    runId: str
    jobId: str | None = None
    phase: str | None = None
    planPreview: dict[str, Any] = Field(default_factory=dict)


class DecentralizedCandidatePreview(BaseModel):
    candidateId: str
    title: str
    conceptSummary: str
    expertRole: str
    expertDomain: str
    expertIntro: str
    styleTags: list[str] = Field(default_factory=list)
    staticHtml: str


class DecentralizedPreviewResponse(BaseModel):
    runId: str
    jobId: str | None = None
    phase: str | None = None
    selectedCandidateId: str | None = None
    candidates: list[DecentralizedCandidatePreview] = Field(default_factory=list)


class DecentralizedSelectionRequest(BaseModel):
    candidateId: str


class DecentralizedDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected"]


class PlayEvent(BaseModel):
    gameId: str
    event: Literal["game_view", "game_start", "game_load_error", "game_end"]
    anonymousId: str | None = None
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    durationMs: int | None = None
    errorMessage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GameInteractionState(BaseModel):
    gameId: str
    likes: int
    favorites: int
    likedByMe: bool
    favoritedByMe: bool


class GameDeleteResult(BaseModel):
    gameId: str
    gameSlug: str
    deleted: bool
    runLogsPreserved: bool = True


class GameVersionSummary(BaseModel):
    versionId: str
    versionNo: int
    runtime: str
    buildStatus: str
    safetyStatus: str
    entryFile: str
    storagePrefix: str
    manifestUrl: str | None = None
    sourceJobId: str | None = None
    current: bool = False
    createdAt: datetime


class GameVersionSwitchRequest(BaseModel):
    versionId: str


class RemixResponse(BaseModel):
    gameId: str
    gameSlug: str
    projectId: str | None = None
    title: str
    status: str


class ProfilePlayRecord(BaseModel):
    eventId: str
    eventType: str
    playedAt: datetime
    game: Game


class ProfileProjectIndex(BaseModel):
    projectId: str
    title: str
    status: str
    gameId: str | None = None
    gameSlug: str | None = None
    latestRunId: str | None = None
    latestRunStatus: str | None = None
    updatedAt: datetime


class ProfileActivity(BaseModel):
    recentPlays: list[ProfilePlayRecord] = Field(default_factory=list)
    projects: list[ProfileProjectIndex] = Field(default_factory=list)


class ProfileRunStepRecord(BaseModel):
    stepNo: int
    stage: str
    status: str
    inputSummary: str | None = None
    outputSummary: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
    recordType: Literal["conversation", "llm", "tool", "lifecycle", "error"]


class ProfileProjectRunFeedback(BaseModel):
    runId: str
    jobId: str | None = None
    status: str
    createType: str
    agentMode: str
    promptSummary: str
    promptFull: str
    llmSummary: str
    llmFull: str
    createdAt: datetime
    completedAt: datetime | None = None
    steps: list[ProfileRunStepRecord] = Field(default_factory=list)


class ProfileProjectDetail(BaseModel):
    project: ProfileProjectIndex
    game: Game | None = None
    runs: list[ProfileProjectRunFeedback] = Field(default_factory=list)


class MaintenanceJob(BaseModel):
    id: str
    status: str
    currentStage: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    promptSummary: str
    creatorId: str | None = None
    creatorEmail: str | None = None
    gameSlug: str | None = None
    createdAt: datetime
    updatedAt: datetime


class MaintenanceOverview(BaseModel):
    jobCounts: dict[str, int] = Field(default_factory=dict)
    failedJobsLast24h: int = 0
    pendingReviews: int = 0
    publicGames: int = 0
    assetsTotal: int = 0
    assetsBytes: int = 0
    recentFailedJobs: list[MaintenanceJob] = Field(default_factory=list)


class MaintenanceRunStep(BaseModel):
    stepNo: int
    stage: str
    status: str
    inputSummary: str | None = None
    outputSummary: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    outputTokens: int | None = None
    createdAt: datetime


class MaintenanceCreateRun(BaseModel):
    runId: str
    jobId: str | None = None
    projectId: str
    projectTitle: str | None = None
    createType: str
    agentMode: str
    status: str
    jobStatus: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    promptSummary: str
    creatorEmail: str | None = None
    gameSlug: str | None = None
    totalOutputTokens: int
    startedAt: datetime
    completedAt: datetime | None = None
    steps: list[MaintenanceRunStep] = Field(default_factory=list)


class MaintenanceGame(BaseModel):
    id: str
    slug: str
    title: str
    description: str | None = None
    visibility: str
    publishStatus: str
    plays: int
    likes: int
    favorites: int
    coverAssetId: str | None = None
    authorId: str | None = None
    updatedAt: datetime


class MaintenanceGameUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    visibility: Literal["private", "unlisted", "public"] | None = None
    publishStatus: Literal["draft", "reviewing", "published", "rejected", "archived"] | None = None


class MaintenanceModerationRequest(BaseModel):
    status: Literal["approved", "rejected"]
    reason: str = ""


class MaintenanceReview(BaseModel):
    id: str
    targetType: str
    targetId: str
    status: str
    reason: str | None = None
    reviewerId: str | None = None
    createdAt: datetime
    reviewedAt: datetime | None = None


class MaintenanceAsset(BaseModel):
    id: str
    kind: str
    bucket: str
    objectKey: str
    publicUrl: str | None = None
    contentType: str | None = None
    sizeBytes: int
    gameId: str | None = None
    versionId: str | None = None
    jobId: str | None = None
    createdAt: datetime
