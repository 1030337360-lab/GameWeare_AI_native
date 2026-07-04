"""
非敏感数据缓存策略：逻辑过期 + 乐观锁
- 缓存击穿时返回旧值
- 适用于商品列表、配置等非敏感数据
"""

import json
import time
import threading
from typing import Callable, TypeVar

import redis
from app.services.auth_service import redis_client


T = TypeVar('T')


class LogicalExpiredCache:
    """逻辑过期缓存"""
    
    def __init__(self, redis_client: redis.Redis):
        self.client = redis_client
        self._local_locks: dict[str, threading.Lock] = {}
        self._lock_master = threading.Lock()
    
    def _get_lock(self, key: str) -> threading.Lock:
        if key not in self._local_locks:
            with self._lock_master:
                if key not in self._local_locks:
                    self._local_locks[key] = threading.Lock()
        return self._local_locks[key]
    
    def get_with_rebuild(
        self,
        cache_key: str,
        rebuild_func: Callable[[], T],
        logical_ttl_seconds: int = 300,
        physical_ttl_seconds: int = 3600,
        lock_timeout_seconds: float = 5.0,
    ) -> T | None:
        client = self.client
        now = time.time()
        
        # 查缓存
        cached_raw = client.get(cache_key)
        
        if cached_raw:
            try:
                cached_data = json.loads(cached_raw)
                value = cached_data.get("value")
                expire_at = cached_data.get("expire_at", 0)
                
                # 未过期，直接返回
                if now < expire_at:
                    return value
                
                # 逻辑过期，尝试重建
                return self._try_rebuild(
                    cache_key, value, rebuild_func,
                    logical_ttl_seconds, physical_ttl_seconds,
                    lock_timeout_seconds, now
                )
            
            except (json.JSONDecodeError, KeyError):
                client.delete(cache_key)
        
        # 缓存不存在，重建
        return self._try_rebuild(
            cache_key, None, rebuild_func,
            logical_ttl_seconds, physical_ttl_seconds,
            lock_timeout_seconds, now
        )
    
    def _try_rebuild(
        self,
        cache_key: str,
        old_value: T | None,
        rebuild_func: Callable[[], T],
        logical_ttl_seconds: int,
        physical_ttl_seconds: int,
        lock_timeout_seconds: float,
        now: float,
    ) -> T | None:
        client = self.client
        lock_key = f"lock:rebuild:{cache_key}"
        
        # 尝试获取分布式锁
        acquired = client.set(lock_key, "1", nx=True, ex=int(lock_timeout_seconds))
        
        if acquired:
            try:
                new_value = rebuild_func()
                
                if new_value is not None:
                    cache_data = {
                        "value": new_value,
                        "expire_at": now + logical_ttl_seconds,
                    }
                    client.setex(
                        cache_key,
                        physical_ttl_seconds,
                        json.dumps(cache_data, default=str)
                    )
                
                return new_value
            
            finally:
                client.delete(lock_key)
        
        else:
            # 未获得锁，返回旧值
            if old_value is not None:
                return old_value
            
            # 无旧值，等待后重试
            time.sleep(0.1)
            return self.get_with_rebuild(
                cache_key, rebuild_func,
                logical_ttl_seconds, physical_ttl_seconds,
                lock_timeout_seconds
            )


# 全局实例
_logical_cache: LogicalExpiredCache | None = None


def get_logical_cache() -> LogicalExpiredCache:
    global _logical_cache
    if _logical_cache is None:
        _logical_cache = LogicalExpiredCache(redis_client())
    return _logical_cache


def get_with_cache_defense(
    cache_key: str,
    rebuild_func: Callable[[], T],
    logical_ttl_seconds: int = 300,
    physical_ttl_seconds: int = 3600,
) -> T | None:
    """
    非敏感数据缓存查询（逻辑过期 + 乐观锁）
    
    Args:
        cache_key: Redis key
        rebuild_func: 重建函数
        logical_ttl_seconds: 逻辑过期时间
        physical_ttl_seconds: 物理过期时间
    
    Returns:
        查询结果或 None
    """
    cache = get_logical_cache()
    return cache.get_with_rebuild(
        cache_key=cache_key,
        rebuild_func=rebuild_func,
        logical_ttl_seconds=logical_ttl_seconds,
        physical_ttl_seconds=physical_ttl_seconds,
    )
