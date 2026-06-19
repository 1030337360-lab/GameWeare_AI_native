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


class CreateJobRequest(BaseModel):
    prompt: str = ""
    files: list[str] = Field(default_factory=list)
    agentMode: Literal["chat", "react", "plan", "init", "opt"] = "chat"
    createType: Literal["init", "opt"] = "init"
    projectId: str | None = None


class AIConfigRequest(BaseModel):
    baseUrl: str
    model: str
    apiKey: str
    provider: str = "fighting"


class AIConfigState(BaseModel):
    authenticated: bool = False
    configured: bool = False
    baseUrl: str | None = None
    model: str | None = None
    provider: str | None = None


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
    latestRunId: str | None = None
    latestRunStatus: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime
    updatedAt: datetime


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


class PlayEvent(BaseModel):
    gameId: str
    event: Literal["game_view", "game_start", "game_load_error", "game_end"]
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    durationMs: int | None = None
    errorMessage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
