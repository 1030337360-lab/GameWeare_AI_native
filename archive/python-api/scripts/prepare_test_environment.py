from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
import redis
from minio import Minio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


TEST_DATABASE_NAME = "gameweare_test"
TEST_MINIO_BUCKET = "gameweare-games-test"
TEST_REDIS_URL = "redis://localhost:6379/15"
INIT_SQL_DIR = Path(__file__).resolve().parents[1] / "db" / "init"


def _admin_database_url() -> str:
    settings = get_settings()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url.rsplit("/", 1)[0] + "/postgres"


def create_test_database(*, reset: bool) -> None:
    with psycopg.connect(_admin_database_url(), autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DATABASE_NAME,)).fetchone()
        if reset and exists:
            connection.execute(
                """
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = %s AND pid <> pg_backend_pid()
""",
                (TEST_DATABASE_NAME,),
            )
            connection.execute(f"DROP DATABASE {TEST_DATABASE_NAME}")
            exists = None
        if not exists:
            connection.execute(f"CREATE DATABASE {TEST_DATABASE_NAME} TEMPLATE template0 ENCODING 'UTF8'")


def seed_test_database() -> None:
    test_url = _admin_database_url().rsplit("/", 1)[0] + f"/{TEST_DATABASE_NAME}"
    with psycopg.connect(test_url, autocommit=True) as connection:
        for path in sorted(INIT_SQL_DIR.glob("*.sql")):
            connection.execute(path.read_text(encoding="utf-8"))


def create_test_bucket(*, reset: bool) -> None:
    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )
    if client.bucket_exists(TEST_MINIO_BUCKET):
        if reset:
            for item in client.list_objects(TEST_MINIO_BUCKET, recursive=True):
                client.remove_object(TEST_MINIO_BUCKET, item.object_name)
        return
    client.make_bucket(TEST_MINIO_BUCKET)


def clear_test_redis() -> None:
    redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True).flushdb()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare isolated resources for mutating API integration tests.")
    parser.add_argument("--reset", action="store_true", help="Drop/recreate the test DB and clear test bucket objects.")
    args = parser.parse_args()

    create_test_database(reset=args.reset)
    seed_test_database()
    create_test_bucket(reset=args.reset)
    clear_test_redis()
    print("Prepared test resources:")
    print(f"- DATABASE_URL=postgresql+psycopg://gameweare:gameweare@localhost:5432/{TEST_DATABASE_NAME}")
    print(f"- MINIO_BUCKET={TEST_MINIO_BUCKET}")
    print(f"- REDIS_URL={TEST_REDIS_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
