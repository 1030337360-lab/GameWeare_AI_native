from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support.integration import configure_test_environment, isolated_integration_test

configure_test_environment()

from app.agents.framework.run_log import RunLog
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.framework.task_state import TaskState
from app.agents.multi_agent import record_multi_agent_contracts, should_run_multi_agent_contracts
from app.database import db_connection


class TaskStoreSpy:
    def __init__(self) -> None:
        self.checkpoints: list[dict] = []

    def checkpoint(self, task_state: TaskState, label: str, payload: dict, latest_log_object_key: str) -> str:
        self.checkpoints.append(
            {
                "runId": task_state.run_id,
                "label": label,
                "payload": payload,
                "latestLogObjectKey": latest_log_object_key,
            }
        )
        return f"task-state/{task_state.run_id}.json"


class Context:
    def __init__(self) -> None:
        ensure_agent_framework_schema()
        self.run_id = str(uuid4())
        self.project_id = str(uuid4())
        self.user_id = str(uuid4())
        with db_connection() as connection:
            user = connection.execute(
                """
INSERT INTO users (id, email, display_name)
VALUES (%s, %s, 'Multi Agent Test User')
RETURNING id
""",
                (self.user_id, f"multi-agent-{uuid4().hex}@gameweare.local"),
            ).fetchone()
            project = connection.execute(
                """
INSERT INTO agent_projects (id, user_id, title, status)
VALUES (%s, %s, 'Multi Agent Test Project', 'active')
RETURNING id
""",
                (self.project_id, user["id"]),
            ).fetchone()
            connection.execute(
                """
INSERT INTO create_runs (id, task_id, project_id, user_id, create_type, agent_mode, status, log_object_key)
VALUES (%s, gen_random_uuid(), %s, %s, 'init', 'decentralized', 'running', %s)
""",
                (self.run_id, project["id"], user["id"], f"agent-runs/{self.run_id}/run-log.jsonl"),
            )
        self.run_log = RunLog(self.run_id)
        self.task_state = TaskState(
            run_id=self.run_id,
            task_id=str(uuid4()),
            project_id=self.project_id,
            user_id=self.user_id,
            user_request="make a racing game",
        )
        self.task_store = TaskStoreSpy()


def run() -> None:
    assert should_run_multi_agent_contracts("decentralized")
    assert not should_run_multi_agent_contracts("react")

    single_context = Context()
    assert record_multi_agent_contracts(single_context, agent_mode="react") == []
    assert single_context.run_log.records == []

    context = Context()
    contracts = record_multi_agent_contracts(context, agent_mode="decentralized")
    assert len(contracts) == 6
    assert [contract["stage"] for contract in contracts] == [
        "planner",
        "asset_agent",
        "game_code_agent",
        "build_agent",
        "safety_agent",
        "publisher_agent",
    ]
    stages = [record["stage"] for record in context.run_log.records]
    assert stages[0] == "multi_agent_orchestration_started"
    assert "multi_agent_planner" in stages
    assert "multi_agent_publisher_agent" in stages
    assert context.task_store.checkpoints[0]["label"] == "multi_agent_contracts_registered"
    assert context.task_store.checkpoints[0]["payload"]["contracts"][0]["outputContract"]["gameBrief"]


if __name__ == "__main__":
    with isolated_integration_test():
        run()
    print("multi-agent orchestration checks passed")
