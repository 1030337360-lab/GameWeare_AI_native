"""
布隆过滤器：防止缓存穿透
"""

import hashlib
import redis


class BloomFilter:
    """布隆过滤器"""

    def __init__(self, redis_client: redis.Redis, key: str, size: int = 1000000, hash_count: int = 5):
        self.client = redis_client
        self.key = key
        self.size = size
        self.hash_count = hash_count
    
    def _hashes(self, item: str) -> list[int]:
        result = []
        for i in range(self.hash_count):
            hash_val = hashlib.md5(f"{item}:{i}".encode()).hexdigest()
            result.append(int(hash_val, 16) % self.size)
        return result
    
    def add(self, item: str) -> None:
        positions = self._hashes(item)
        for pos in positions:
            self.client.setbit(self.key, pos, 1)
    
    def exists(self, item: str) -> bool:
        positions = self._hashes(item)
        for pos in positions:
            if not self.client.getbit(self.key, pos):
                return False
        return True

# 全局实例
_user_bloom_filter: BloomFilter | None = None


def get_user_bloom_filter() -> BloomFilter:
    global _user_bloom_filter
    if _user_bloom_filter is None:
        from app.services.auth_service import redis_client
        _user_bloom_filter = BloomFilter(
            redis_client(),
            key="bloom:user:exists",
            size=1000000,
            hash_count=5
        )
    return _user_bloom_filter
