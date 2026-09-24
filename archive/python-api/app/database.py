from collections.abc import Iterator
from contextlib import contextmanager
import atexit

import psycopg
from psycopg.rows import dict_row
from psycopg import Connection
from psycopg_pool import ConnectionPool

from app.config import get_settings

_pool: ConnectionPool | None = None

def init_pool(
        conninfo: str,
        *,
        min_size: int = 5,
        max_size: int = 10,
        max_idle: float = 300.0,  # 5 分钟
        max_lifetime: float = 3600.0,       # 1 小时
        timeout: float = 30.0,              # 获取连接超时
) -> ConnectionPool:
    global _pool
    clean_conninfo = conninfo.replace("postgresql+psycopg://", "postgresql://", 1)
    _pool = ConnectionPool(
        conninfo=clean_conninfo,
        min_size=min_size,
        max_size=max_size,
        max_idle=max_idle,
        max_lifetime=max_lifetime,
        timeout=timeout,
    )
    _pool.wait()
    return _pool

def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool

def get_db():
    """FastAPI 依赖：从连接池获取连接。"""
    pool = get_pool()
    with pool.connection() as conn:
        yield conn

def close_pool() -> None:
    """关闭连接池，应用关闭时调用。"""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None

atexit.register(close_pool)

def psycopg_url() -> str:
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@contextmanager
def db_connection() -> Iterator[psycopg.Connection]:
    with psycopg.connect(psycopg_url(), row_factory=dict_row) as connection:
        yield connection
