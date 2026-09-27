package com.gameweare.api.catalog;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import java.util.function.Supplier;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

@Service
public class GameCatalogCache {
    private static final DefaultRedisScript<Long> UNLOCK = new DefaultRedisScript<>(
            "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end",
            Long.class);
    private final StringRedisTemplate redis;
    private final ObjectMapper json;

    public GameCatalogCache(StringRedisTemplate redis, ObjectMapper json) { this.redis = redis; this.json = json; }

    @SuppressWarnings("unchecked")
    public Map<String, Object> publicGame(String slug, Supplier<Map<String, Object>> loader) {
        String key = "game:public:" + slug;
        try {
            String cached = redis.opsForValue().get(key);
            if ("!".equals(cached)) return null;
            if (cached != null) return json.readValue(cached, Map.class);
            String lock = "game:public:lock:" + slug;
            String owner = UUID.randomUUID().toString();
            boolean acquired = Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(lock, owner, Duration.ofSeconds(10)));
            if (!acquired) {
                for (int n = 0; n < 4; n++) {
                    Thread.sleep(25);
                    cached = redis.opsForValue().get(key);
                    if ("!".equals(cached)) return null;
                    if (cached != null) return json.readValue(cached, Map.class);
                }
                return loader.get();
            }
            try {
                Map<String, Object> loaded = loader.get();
                if (loaded == null) redis.opsForValue().set(key, "!", Duration.ofSeconds(10));
                else redis.opsForValue().set(key, json.writeValueAsString(loaded),
                        Duration.ofSeconds(60 + ThreadLocalRandom.current().nextInt(61)));
                return loaded;
            } finally {
                redis.execute(UNLOCK, java.util.List.of(lock), owner);
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return loader.get();
        } catch (Exception unavailable) {
            return loader.get();
        }
    }

    public void invalidate(String slug) {
        try { redis.delete("game:public:" + slug); }
        catch (RuntimeException ignored) { /* Short TTL and MySQL visibility check bound staleness. */ }
    }
}
