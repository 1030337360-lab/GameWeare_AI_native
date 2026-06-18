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


class AgentLog(BaseModel):
    stage: str
    status: Literal["pending", "running", "succeeded", "failed", "skipped", "completed"]
    message: str


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


class PlayEvent(BaseModel):
    gameId: str
    event: Literal["game_view", "game_start", "game_load_error", "game_end"]
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    durationMs: int | None = None
    errorMessage: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
