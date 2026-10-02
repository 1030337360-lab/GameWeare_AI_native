package com.gameweare.api.catalog;

import org.junit.jupiter.api.Test;
import org.redisson.api.RBloomFilter;
import org.redisson.api.RBucket;
import org.redisson.api.RedissonClient;
import com.gameweare.api.catalog.dao.GameStatsMapper;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.RedisCallback;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class GameSlugBloomFilterTest {
    @Test
    void onlySeededFilterMayRejectAndRedisFailureFallsBack() {
        RedissonClient redis = mock(RedissonClient.class);
        @SuppressWarnings("unchecked") RBucket<String> ready = mock(RBucket.class);
        @SuppressWarnings("unchecked") RBloomFilter<String> filter = mock(RBloomFilter.class);
        StringRedisTemplate info = mock(StringRedisTemplate.class);
        Properties props = new Properties();
        props.setProperty("run_id", "redis-boot-1");
        doReturn(props).when(info).execute(any(RedisCallback.class));
        when(redis.<String>getBucket("game:public:slugs:ready:v2")).thenReturn(ready);
        when(redis.<String>getBloomFilter("game:public:slugs:v1")).thenReturn(filter);
        GameSlugBloomFilter bloom = new GameSlugBloomFilter(redis, mock(GameStatsMapper.class), info);
        assertTrue(bloom.mightContain("missing"));
        verifyNoInteractions(filter);
        when(ready.get()).thenReturn("redis-boot-1");
        assertFalse(bloom.mightContain("missing"));
        when(ready.get()).thenReturn("redis-boot-0");
        assertTrue(bloom.mightContain("missing"));
        when(ready.get()).thenThrow(new IllegalStateException("Redis unavailable"));
        assertTrue(bloom.mightContain("missing"));
    }

    @Test
    void publishAddsSlugBeforeDatabaseTransition() {
        RedissonClient redis = mock(RedissonClient.class);
        @SuppressWarnings("unchecked") RBloomFilter<String> filter = mock(RBloomFilter.class);
        when(redis.<String>getBloomFilter("game:public:slugs:v1")).thenReturn(filter);
        new GameSlugBloomFilter(redis, mock(GameStatsMapper.class),
                mock(StringRedisTemplate.class)).addBeforePublish("game-1");
        verify(filter).add("game-1");
    }
}
