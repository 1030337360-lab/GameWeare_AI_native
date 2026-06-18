from datetime import datetime, timezone
from typing import Literal

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


class SessionState(BaseModel):
    authenticated: bool = False
    user: dict | None = None


class CreateJobRequest(BaseModel):
    prompt: str = ""
    files: list[str] = Field(default_factory=list)


class AgentLog(BaseModel):
    stage: str
    status: Literal["pending", "completed", "skipped"]
    message: str


class CreateJob(BaseModel):
    id: str
    status: Literal["stubbed"]
    prompt: str
    createdAt: datetime
    logs: list[AgentLog]


class PlayEvent(BaseModel):
    gameId: str
    event: str
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
