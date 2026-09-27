package com.gameweare.api.catalog;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
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
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    public GameTrendingService(JdbcTemplate jdbc, StringRedisTemplate redis) {
        this.jdbc = jdbc; this.redis = redis;
    }

    public void refresh(String gameId) {
        try {
            List<Map<String, Object>> games = jdbc.queryForList("""
                    SELECT plays_count,likes_count,favorites_count,publish_status,visibility FROM games WHERE id=?
                    """, gameId);
            if (games.isEmpty() || !"published".equals(games.get(0).get("publish_status"))
                    || !"public".equals(games.get(0).get("visibility"))) {
                redis.opsForZSet().remove(KEY, gameId); return;
            }
            Map<String, Object> row = games.get(0);
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
        if (ids.isEmpty()) return jdbc.queryForList("""
                SELECT g.slug AS id,g.title,u.display_name AS author,
                       g.plays_count AS plays,g.likes_count AS likes,g.favorites_count AS favorites
                FROM games g JOIN users u ON u.id=g.author_id
                WHERE g.publish_status='published' AND g.visibility='public'
                ORDER BY (g.plays_count+3*g.likes_count+5*g.favorites_count) DESC,g.published_at DESC LIMIT ?
                """, limit);
        List<Map<String, Object>> result = new ArrayList<>();
        for (String id : ids) {
            List<Map<String, Object>> rows = jdbc.queryForList("""
                    SELECT g.slug AS id,g.title,u.display_name AS author,
                           g.plays_count AS plays,g.likes_count AS likes,g.favorites_count AS favorites
                    FROM games g JOIN users u ON u.id=g.author_id
                    WHERE g.id=? AND g.publish_status='published' AND g.visibility='public'
                    """, id);
            if (!rows.isEmpty()) result.add(rows.get(0));
            if (result.size() >= limit) break;
        }
        return result;
    }

    @Scheduled(initialDelay = 30_000, fixedDelay = 600_000)
    public void rebuild() {
        try {
            List<Map<String, Object>> games = jdbc.queryForList("""
                    SELECT id,plays_count,likes_count,favorites_count FROM games
                    WHERE publish_status='published' AND visibility='public'
                    ORDER BY (plays_count+3*likes_count+5*favorites_count) DESC LIMIT 1000
                    """);
            redis.delete(KEY);
            for (Map<String, Object> row : games) {
                double score = ((Number) row.get("plays_count")).doubleValue()
                        + 3 * ((Number) row.get("likes_count")).doubleValue()
                        + 5 * ((Number) row.get("favorites_count")).doubleValue();
                redis.opsForZSet().add(KEY, row.get("id").toString(), score);
            }
        } catch (RuntimeException ignored) { /* Reads fall back to SQL. */ }
    }
}
