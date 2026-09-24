from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import create_service


class FakeMinio:
    def __init__(self) -> None:
        self.removed: list[tuple[str, str]] = []

    def remove_object(self, bucket: str, object_key: str) -> None:
        self.removed.append((bucket, object_key))


class FakeRedis:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, key: str) -> None:
        self.deleted.append(key)


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.calls.append((sql, params))


class FakeDb:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeConnection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def run() -> None:
    fake_minio = FakeMinio()
    fake_redis = FakeRedis()
    fake_connection = FakeConnection()

    create_service._minio_client = lambda: fake_minio  # type: ignore[assignment]
    create_service.redis_client = lambda: fake_redis  # type: ignore[assignment]
    create_service.db_connection = lambda: FakeDb(fake_connection)  # type: ignore[assignment]

    create_service._cleanup_failed_input_assets(
        job_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        input_assets=[
            {
                "assetId": "00000000-0000-0000-0000-000000000003",
                "objectKey": "uploads/user/create-input/asset/sketch.png",
            }
        ],
    )

    assert fake_minio.removed == [("gameweare-games", "uploads/user/create-input/asset/sketch.png")]
    assert fake_redis.deleted == ["create:input-assets:00000000-0000-0000-0000-000000000001"]
    executed_sql = "\n".join(sql for sql, _params in fake_connection.calls)
    assert "DELETE FROM assets" in executed_sql
    assert "inputAssets" in executed_sql

    from app.services.profile_service import _sanitize_metric

    sanitized = _sanitize_metric(
        {
            "apiKey": "secret-key",
            "Authorization": "Bearer token",
            "image_url": "data:image/png;base64,AAAA",
            "nested": {"refresh_token": "secret-token", "text": "ok"},
        }
    )
    assert sanitized["apiKey"] == "[redacted]"
    assert sanitized["Authorization"] == "[redacted]"
    assert sanitized["image_url"] == "[redacted-image]"
    assert sanitized["nested"]["refresh_token"] == "[redacted]"
    assert sanitized["nested"]["text"] == "ok"


if __name__ == "__main__":
    run()
    print("multimodal helper checks passed")
