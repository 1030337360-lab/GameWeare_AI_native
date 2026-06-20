from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse


API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg://yahaha:yahaha@localhost:5432/yahaha_test"
DEFAULT_TEST_REDIS_URL = "redis://localhost:6379/15"
DEFAULT_TEST_MINIO_BUCKET = "yahaha-games-test"
LOCK_FILE = API_ROOT / ".integration-test.lock"
LOCK_STALE_SECONDS = 30 * 60


def configure_test_environment() -> None:
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("YAHAHA_TESTING", "1")
    os.environ.setdefault("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    os.environ.setdefault("REDIS_URL", DEFAULT_TEST_REDIS_URL)
    os.environ.setdefault("MINIO_BUCKET", DEFAULT_TEST_MINIO_BUCKET)
    os.environ.setdefault("MINIO_PUBLIC_BASE_URL", f"http://localhost:9000/{DEFAULT_TEST_MINIO_BUCKET}")
    os.environ.setdefault("MAINTAINER_EMAIL", "maintainer-test@yahaha.local")
    os.environ.setdefault("MAINTAINER_PASSWORD", "password123")
    os.environ.setdefault("CREATE_VALIDATE_LLM_CONFIG", "false")


def _db_name(database_url: str) -> str:
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    return parsed.path.rsplit("/", 1)[-1]


def assert_safe_test_environment() -> None:
    configure_test_environment()
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    db_name = _db_name(settings.database_url)
    redis_db = urlparse(settings.redis_url).path.strip("/") or "0"
    errors = []
    if "test" not in db_name.lower():
        errors.append(f"DATABASE_URL must point to a test database, got database '{db_name}'.")
    if settings.minio_bucket == "yahaha-games" or "test" not in settings.minio_bucket.lower():
        errors.append(f"MINIO_BUCKET must be a test bucket, got '{settings.minio_bucket}'.")
    if redis_db == "0":
        errors.append("REDIS_URL must not use Redis DB 0 for mutating integration tests.")
    if errors:
        raise RuntimeError("Unsafe integration test environment:\n- " + "\n- ".join(errors))


def cleanup_test_pollution(*, quiet: bool = True) -> None:
    from scripts.cleanup_test_pollution import cleanup_test_pollution as cleanup

    cleanup(apply=True, quiet=quiet)


@contextmanager
def integration_test_lock() -> Iterator[None]:
    while True:
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - LOCK_FILE.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    LOCK_FILE.unlink()
                    continue
            except FileNotFoundError:
                continue
            time.sleep(0.25)
    try:
        yield
    finally:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def isolated_integration_test() -> Iterator[None]:
    assert_safe_test_environment()
    with integration_test_lock():
        cleanup_test_pollution(quiet=True)
        try:
            yield
        finally:
            cleanup_test_pollution(quiet=True)


def isolated_run(run_fn) -> None:
    with isolated_integration_test():
        run_fn()
