package com.gameweare.api.catalog;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.redisson.api.RedissonClient;
import org.redisson.api.RTopic;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.*;

class GameCatalogCacheLayersTest {
    @Test
    void caffeineServesSecondReadAndInvalidationForcesRedisRead() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked") ValueOperations<String, String> values = mock(ValueOperations.class);
        RedissonClient redisson = mock(RedissonClient.class);
        RTopic topic = mock(RTopic.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get("game:public:demo")).thenReturn("{\"title\":\"Demo\"}");
        when(redisson.getTopic("game:public:invalidate")).thenReturn(topic);
        GameCatalogCache cache = new GameCatalogCache(redis, redisson, new ObjectMapper());
        assertEquals("Demo", cache.publicGame("demo", () -> Map.of("title", "wrong")).get("title"));
        assertEquals("Demo", cache.publicGame("demo", () -> Map.of("title", "wrong")).get("title"));
        verify(values, times(1)).get("game:public:demo");
        cache.invalidate("demo");
        assertEquals("Demo", cache.publicGame("demo", () -> Map.of("title", "wrong")).get("title"));
        verify(values, times(2)).get("game:public:demo");
        verify(topic).publish("demo");
    }
}
