package com.gameweare.api.catalog;

import java.util.List;
import java.util.Properties;
import java.util.concurrent.TimeUnit;
import org.redisson.api.RBloomFilter;
import org.redisson.api.RedissonClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Only a fully seeded, shared filter may reject a slug; Redis failures always fall back to MySQL. */
@Component
public class GameSlugBloomFilter {
    private static final Logger LOG = LoggerFactory.getLogger(GameSlugBloomFilter.class);
    private static final String FILTER = "game:public:slugs:v1";
    private static final String READY = "game:public:slugs:ready:v2";
    private final RedissonClient redis;
    private final JdbcTemplate db;
    private final StringRedisTemplate redisInfo;

    public GameSlugBloomFilter(RedissonClient redis, JdbcTemplate db, StringRedisTemplate redisInfo) {
        this.redis = redis;
        this.db = db;
        this.redisInfo = redisInfo;
    }

    @EventListener(ApplicationReadyEvent.class)
    @Scheduled(fixedDelay = 300_000)
    public void seedIfNeeded() {
        try {
            String runId = currentRedisRunId();
            if (runId.equals(redis.<String>getBucket(READY).get())) return;
            var lock = redis.getLock(FILTER + ":seed-lock");
            if (!lock.tryLock(0, TimeUnit.SECONDS)) return;
            try {
                runId = currentRedisRunId();
                if (runId.equals(redis.<String>getBucket(READY).get())) return;
                RBloomFilter<String> filter = redis.getBloomFilter(FILTER);
                filter.tryInit(1_000_000L, 0.01);
                List<String> slugs = db.queryForList(
                        "SELECT slug FROM games WHERE publish_status='published' AND visibility='public'", String.class);
                for (String slug : slugs) filter.add(slug);
                redis.<String>getBucket(READY).set(runId);
                LOG.info("Public game Bloom filter ready with {} existing slugs", slugs.size());
            } finally {
                if (lock.isHeldByCurrentThread()) lock.unlock();
            }
        } catch (Exception unavailable) {
            LOG.warn("Bloom filter unavailable; game lookup continues through MySQL", unavailable);
        }
    }

    public boolean mightContain(String slug) {
        try {
            String runId = currentRedisRunId();
            if (!runId.equals(redis.<String>getBucket(READY).get())) return true;
            return redis.<String>getBloomFilter(FILTER).contains(slug);
        } catch (Exception unavailable) {
            return true;
        }
    }

    /** Call before publishing. A failed insert must abort publication to avoid a false negative. */
    public void addBeforePublish(String slug) {
        RBloomFilter<String> filter = redis.getBloomFilter(FILTER);
        filter.tryInit(1_000_000L, 0.01);
        filter.add(slug);
    }

    private String currentRedisRunId() {
        Properties info = redisInfo.execute((RedisCallback<Properties>)
                connection -> connection.serverCommands().info("server"));
        String runId = info == null ? null : info.getProperty("run_id");
        if (runId == null || runId.isBlank()) throw new IllegalStateException("Redis run_id unavailable");
        return runId;
    }
}
