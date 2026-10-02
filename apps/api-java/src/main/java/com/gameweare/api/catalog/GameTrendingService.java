package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.GameStatsMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/games/trending")
class TrendingController {
    private final GameTrendingService trending;
    TrendingController(GameTrendingService trending) { this.trending = trending; }
    @GetMapping
    public List<Map<String, Object>> list(@RequestParam(defaultValue = "20") int limit) {
        return trending.list(Math.max(1, Math.min(limit, 50)));
    }
}

@Service
public class GameTrendingService {
    private static final String KEY = "game:trending";
    private final GameStatsMapper games;
    private final StringRedisTemplate redis;
    public GameTrendingService(GameStatsMapper games, StringRedisTemplate redis) {
        this.games = games; this.redis = redis;
    }

    public void refresh(String gameId) {
        try {
            Map<String, Object> row = games.counters(gameId);
            if (row == null || !"published".equals(row.get("publish_status"))
                    || !"public".equals(row.get("visibility"))) {
                redis.opsForZSet().remove(KEY, gameId); return;
            }
            double score = ((Number) row.get("plays_count")).doubleValue()
                    + 3 * ((Number) row.get("likes_count")).doubleValue()
                    + 5 * ((Number) row.get("favorites_count")).doubleValue();
            redis.opsForZSet().add(KEY, gameId, score);
        } catch (RuntimeException ignored) { /* MySQL counters remain authoritative. */ }
    }

    public List<Map<String, Object>> list(int limit) {
        List<String> ids = new ArrayList<>();
        try {
            var top = redis.opsForZSet().reverseRange(KEY, 0, Math.max(limit * 2L, 50));
            if (top != null) ids.addAll(top);
        } catch (RuntimeException ignored) { }
        if (ids.isEmpty()) return games.topGames(limit);
        List<Map<String, Object>> result = new ArrayList<>();
        for (String id : ids) {
            Map<String, Object> row = games.publicGameSummary(id);
            if (row != null) result.add(row);
            if (result.size() >= limit) break;
        }
        return result;
    }

    @Scheduled(initialDelay = 30_000, fixedDelay = 600_000)
    public void rebuild() {
        try {
            List<Map<String, Object>> top = games.topCounters();
            redis.delete(KEY);
            for (Map<String, Object> row : top) {
                double score = ((Number) row.get("plays_count")).doubleValue()
                        + 3 * ((Number) row.get("likes_count")).doubleValue()
                        + 5 * ((Number) row.get("favorites_count")).doubleValue();
                redis.opsForZSet().add(KEY, row.get("id").toString(), score);
            }
        } catch (RuntimeException ignored) { /* Reads fall back to SQL. */ }
    }
}
