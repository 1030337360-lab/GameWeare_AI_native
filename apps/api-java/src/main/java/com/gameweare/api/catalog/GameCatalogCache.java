package com.gameweare.api.catalog;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

@Service
public class GameCatalogCache {
    private static final String CHANNEL = "game:public:invalidate";
    private static final String ABSENT = "!";
    private final Cache<String, String> local = Caffeine.newBuilder().maximumSize(10_000)
            .expireAfterWrite(Duration.ofSeconds(3)).build();
    private final StringRedisTemplate redis;
    private final RedissonClient redisson;
    private final ObjectMapper json;
    private int topicListenerId = -1;
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private GameSlugBloomFilter bloom;

    public GameCatalogCache(StringRedisTemplate redis, RedissonClient redisson, ObjectMapper json) {
        this.redis = redis; this.redisson = redisson; this.json = json;
    }

    @PostConstruct
    void subscribe() {
        topicListenerId = redisson.getTopic(CHANNEL).addListener(String.class,
                (channel, slug) -> local.invalidate(key(slug)));
    }

    @PreDestroy
    void unsubscribe() {
        if (topicListenerId >= 0) redisson.getTopic(CHANNEL).removeListener(topicListenerId);
    }

    @SuppressWarnings("unchecked")
    public Map<String, Object> publicGame(String slug, Supplier<Map<String, Object>> loader) {
        String key = key(slug);
        try {
            String cached = local.getIfPresent(key);
            if (cached == null) cached = redis.opsForValue().get(key);
            if (cached != null) {
                local.put(key, cached);
                return ABSENT.equals(cached) ? null : json.readValue(cached, Map.class);
            }
            RLock lock = redisson.getLock(key + ":rebuild");
            if (!lock.tryLock(0, TimeUnit.SECONDS)) {
                for (int n = 0; n < 4; n++) {
                    Thread.sleep(25);
                    cached = redis.opsForValue().get(key);
                    if (cached != null) {
                        local.put(key, cached);
                        return ABSENT.equals(cached) ? null : json.readValue(cached, Map.class);
                    }
                }
                return loader.get();
            }
            try {
                cached = redis.opsForValue().get(key);
                if (cached != null) {
                    local.put(key, cached);
                    return ABSENT.equals(cached) ? null : json.readValue(cached, Map.class);
                }
                Map<String, Object> loaded = loader.get();
                String encoded = loaded == null ? ABSENT : json.writeValueAsString(loaded);
                Duration ttl = loaded == null ? Duration.ofSeconds(10)
                        : Duration.ofSeconds(60 + ThreadLocalRandom.current().nextInt(61));
                redis.opsForValue().set(key, encoded, ttl);
                local.put(key, encoded);
                return loaded;
            } finally {
                if (lock.isHeldByCurrentThread()) lock.unlock();
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            return loader.get();
        } catch (Exception unavailable) {
            local.invalidate(key);
            return loader.get();
        }
    }

    public void invalidate(String slug) {
        String key = key(slug);
        local.invalidate(key);
        try {
            redis.delete(key);
            redisson.getTopic(CHANNEL).publish(slug);
        }
        catch (RuntimeException ignored) { /* Short TTL and MySQL visibility check bound staleness. */ }
    }

    public boolean mightContain(String slug) { return bloom == null || bloom.mightContain(slug); }

    public void addBeforePublish(String slug) {
        if (bloom != null) bloom.addBeforePublish(slug);
    }

    private static String key(String slug) { return "game:public:" + slug; }
}
