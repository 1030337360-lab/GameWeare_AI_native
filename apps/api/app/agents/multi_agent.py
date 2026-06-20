from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PRODUCTION_AGENT_MODES = {"decentralized"}


@dataclass(frozen=True)
class AgentStageContract:
    stage: str
    role: str
    input_contract: dict[str, str]
    output_contract: dict[str, str]
    retry_policy: dict[str, int | str]
    handoff: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "role": self.role,
            "inputContract": self.input_contract,
            "outputContract": self.output_contract,
            "retryPolicy": self.retry_policy,
            "handoff": self.handoff,
        }


MULTI_AGENT_CONTRACTS: tuple[AgentStageContract, ...] = (
    AgentStageContract(
        stage="planner",
        role="Planner Agent",
        input_contract={
            "userRequest": "Original create request.",
            "memorySummary": "Relevant project/user memory.",
            "workspaceBoundary": "Isolated worktree path.",
        },
        output_contract={
            "gameBrief": "Title, genre, controls, camera, win/lose loop.",
            "taskGraph": "Ordered production stages with dependencies.",
            "acceptanceCriteria": "Playable and safety criteria for publish.",
        },
        retry_policy={"maxAttempts": 2, "onFailure": "fail_run"},
        handoff="asset_agent",
    ),
    AgentStageContract(
        stage="asset_agent",
        role="Asset Agent",
        input_contract={
            "gameBrief": "Planner output.",
            "inputAssets": "User uploaded image/audio/video indexes when available.",
            "styleTags": "Visual and UX tags.",
        },
        output_contract={
            "assetManifest": "Canvas/static asset plan and generated cover contract.",
            "coverSpec": "Durable catalog cover requirements.",
        },
        retry_policy={"maxAttempts": 2, "onFailure": "fail_run"},
        handoff="game_code_agent",
    ),
    AgentStageContract(
        stage="game_code_agent",
        role="GameCode Agent",
        input_contract={
            "gameBrief": "Planner output.",
            "assetManifest": "Asset Agent output.",
            "workspaceBoundary": "Writable isolated workspace.",
        },
        output_contract={
            "files": "index.html and optional support files.",
            "implementationSummary": "Core mechanics implemented.",
            "safetyNotes": "Browser capability notes.",
        },
        retry_policy={"maxAttempts": 2, "onFailure": "send_to_planner_for_repair"},
        handoff="build_agent",
    ),
    AgentStageContract(
        stage="build_agent",
        role="Build Agent",
        input_contract={
            "files": "Generated game files.",
            "workspaceBoundary": "Writable isolated workspace.",
        },
        output_contract={
            "artifactList": "Final files ready for storage.",
            "entryFile": "Playable HTML entry path.",
            "runtime": "iframe-srcdoc or iframe-html5.",
        },
        retry_policy={"maxAttempts": 1, "onFailure": "send_to_game_code_agent_for_repair"},
        handoff="safety_agent",
    ),
    AgentStageContract(
        stage="safety_agent",
        role="Safety Agent",
        input_contract={
            "artifactList": "Build Agent output.",
            "policy": "Yahaha iframe and storage safety policy.",
        },
        output_contract={
            "passed": "Boolean safety decision.",
            "issues": "Structured blocking or warning issues.",
        },
        retry_policy={"maxAttempts": 1, "onFailure": "fail_run"},
        handoff="publisher_agent",
    ),
    AgentStageContract(
        stage="publisher_agent",
        role="Publisher Agent",
        input_contract={
            "artifactList": "Safety-passed artifact list.",
            "databaseContext": "Game, version, asset, project IDs.",
        },
        output_contract={
            "storagePrefix": "MinIO object prefix.",
            "publishedGame": "Game slug, version, manifest, cover URL.",
            "auditSummary": "Run-log summary for reproduction.",
        },
        retry_policy={"maxAttempts": 1, "onFailure": "fail_run"},
        handoff="completed",
    ),
)


def should_run_multi_agent_contracts(agent_mode: str) -> bool:
    return (agent_mode or "").strip().lower() in PRODUCTION_AGENT_MODES


def multi_agent_contract_summary() -> list[dict[str, Any]]:
    return [contract.to_dict() for contract in MULTI_AGENT_CONTRACTS]


def record_multi_agent_contracts(context: Any, *, agent_mode: str) -> list[dict[str, Any]]:
    if not should_run_multi_agent_contracts(agent_mode):
        return []

    contracts = multi_agent_contract_summary()
    context.run_log.append(
        stage="multi_agent_orchestration_started",
        status="succeeded",
        input_summary="Production multi-agent mode selected.",
        output_summary="Planner/Asset/GameCode/Build/Safety/Publisher contracts registered for this run.",
        metrics={"agentMode": agent_mode, "stageCount": len(contracts), "contracts": contracts},
    )
    for order, contract in enumerate(MULTI_AGENT_CONTRACTS, start=1):
        context.run_log.append(
            stage=f"multi_agent_{contract.stage}",
            status="succeeded",
            input_summary=f"{contract.role} input/output contract prepared.",
            output_summary=f"Handoff target: {contract.handoff}.",
            metrics={"order": order, **contract.to_dict()},
        )
    context.task_store.checkpoint(
        context.task_state,
        "multi_agent_contracts_registered",
        {"agentMode": agent_mode, "contracts": contracts},
        context.run_log.object_key,
    )
    return contracts
