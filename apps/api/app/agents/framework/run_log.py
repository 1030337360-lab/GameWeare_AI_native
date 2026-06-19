from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from app.database import db_connection
from app.agents.framework.storage import put_jsonl_object


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunLog:
    run_id: str
    records: list[dict[str, Any]] = field(default_factory=list)
    step_no: int = 0

    @property
    def object_key(self) -> str:
        return f"agent-runs/{self.run_id}/run-log.jsonl"

    def append(
        self,
        *,
        stage: str,
        status: str,
        input_summary: str = "",
        output_summary: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.step_no += 1
        record = {
            "runId": self.run_id,
            "stepNo": self.step_no,
            "stage": stage,
            "status": status,
            "inputSummary": input_summary,
            "outputSummary": output_summary,
            "metrics": metrics or {},
            "createdAt": _now_iso(),
        }
        self.records.append(record)
        with db_connection() as connection:
            connection.execute(
                """
INSERT INTO create_run_steps (
  run_id, step_no, stage, status, input_summary, output_summary, metrics
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_id, step_no) DO UPDATE SET
  stage = EXCLUDED.stage,
  status = EXCLUDED.status,
  input_summary = EXCLUDED.input_summary,
  output_summary = EXCLUDED.output_summary,
  metrics = EXCLUDED.metrics
""",
                (
                    self.run_id,
                    self.step_no,
                    stage,
                    status,
                    input_summary,
                    output_summary,
                    Jsonb(metrics or {}),
                ),
            )
        self.flush()
        return record

    def flush(self) -> str:
        put_jsonl_object(self.object_key, self.records)
        return self.object_key
