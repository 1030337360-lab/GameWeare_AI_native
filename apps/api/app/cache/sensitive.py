"""
敏感数据缓存策略：循环等待
- 缓存击穿时循环等待重建完成
- 确保数据一致性
- 适用于 Token、用户信息等敏感数据
"""

import json
import time
import threading
from typing import Callable, TypeVar

import redis
from app.services.auth_service import redis_client

from app.cache.bloom_filter import get_user_bloom_filter


T = TypeVar('T')


class SensitiveCache:
    """敏感数据缓存（循环等待）"""
    
    def __init__(self, redis_client: redis.Redis):
        self.client = redis_client
    
    def get_with_wait(
        self,
        cache_key: str,
        rebuild_func: Callable[[], T],
        ttl_seconds: int = 300,
        max_wait_seconds: float = 10.0,
        poll_interval: float = 0.1,
    ) -> T | None:
        client = self.client
        lock_key = f"lock:rebuild:{cache_key}"
        bloom = get_user_bloom_filter()
        if not bloom.exists(locals):
            return None
        start_time = time.time()
        
        while True:
            # 查缓存
            cached_raw = client.get(cache_key)
            
            if cached_raw:
                try:
                    cached_data = json.loads(cached_raw)
                    return cached_data.get("value")
                except json.JSONDecodeError:
                    client.delete(cache_key)
            
            # 尝试获取重建锁
            acquired = client.set(lock_key, "1", nx=True, ex=10)
            
            if acquired:
                # 获得重建权
                try:
                    new_value = rebuild_func()
                    
                    if new_value is not None:
                        cache_data = {
                            "value": new_value,
                            "timestamp": time.time(),
                        }
                        client.setex(cache_key, ttl_seconds, json.dumps(cache_data, default=str))
                    
                    return new_value
                
                finally:
                    client.delete(lock_key)
            
            else:
                # 未获得锁，等待后重试
                if time.time() - start_time > max_wait_seconds:
                    # 超时，尝试直接读缓存
                    cached_raw = client.get(cache_key)
                    if cached_raw:
                        try:
                            cached_data = json.loads(cached_raw)
                            return cached_data.get("value")
                        except json.JSONDecodeError:
                            pass
                    
                    return None
                
                time.sleep(poll_interval)


# 全局实例
_sensitive_cache: SensitiveCache | None = None


def get_sensitive_cache() -> SensitiveCache:
    global _sensitive_cache
    if _sensitive_cache is None:
        _sensitive_cache = SensitiveCache(redis_client())
    return _sensitive_cache


def get_with_sensitive_cache(
    cache_key: str,
    rebuild_func: Callable[[], T],
    ttl_seconds: int = 300,
    max_wait_seconds: float = 10.0,
) -> T | None:
    """
    敏感数据缓存查询（循环等待版本）
    
    Args:
        cache_key: Redis key
        rebuild_func: 重建函数
        ttl_seconds: 缓存 TTL
        max_wait_seconds: 最大等待时间
    
    Returns:
        查询结果或 None
    """
    cache = get_sensitive_cache()
    return cache.get_with_wait(
        cache_key=cache_key,
        rebuild_func=rebuild_func,
        ttl_seconds=ttl_seconds,
        max_wait_seconds=max_wait_seconds,
    )
