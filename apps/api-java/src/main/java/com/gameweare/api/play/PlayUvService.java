package com.gameweare.api.play;

import java.time.LocalDate;
import java.time.ZoneOffset;
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
@RequestMapping("/maintenance/analytics/uv")
class PlayUvController {
    private final PlayUvService uv;
    PlayUvController(PlayUvService uv) { this.uv = uv; }
    @GetMapping
    public Map<String, Object> count(@RequestParam(required = false) String day,
                                     @RequestParam(required = false) String gameId) {
        LocalDate date = day == null ? LocalDate.now(ZoneOffset.UTC) : LocalDate.parse(day);
        return uv.count(date, gameId);
    }
}

@Service
public class PlayUvService {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    public PlayUvService(JdbcTemplate jdbc, StringRedisTemplate redis) { this.jdbc = jdbc; this.redis = redis; }

    public void record(String gameId, String userId, String anonymousId) {
        String identity = userId == null ? anonymousId == null ? null : "a:" + anonymousId : "u:" + userId;
        if (identity == null) return;
        LocalDate today = LocalDate.now(ZoneOffset.UTC);
        try {
            redis.opsForHyperLogLog().add("uv:global:" + today, identity);
            redis.opsForHyperLogLog().add("uv:game:" + gameId + ":" + today, identity);
            redis.expire("uv:global:" + today, java.time.Duration.ofDays(90));
            redis.expire("uv:game:" + gameId + ":" + today, java.time.Duration.ofDays(90));
        } catch (RuntimeException ignored) { /* Analytics must not break play. */ }
    }

    public Map<String, Object> count(LocalDate day, String gameId) {
        String key = gameId == null ? "uv:global:" + day : "uv:game:" + gameId + ":" + day;
        try {
            Long approximate = redis.opsForHyperLogLog().size(key);
            return Map.of("day", day.toString(), "gameId", gameId == null ? "all" : gameId,
                    "uv", approximate == null ? 0 : approximate, "approximate", true);
        } catch (RuntimeException unavailable) {
            String sql = "SELECT COUNT(DISTINCT COALESCE(CONCAT('u:',user_id),CONCAT('a:',anonymous_id))) "
                    + "FROM play_events WHERE created_at>=? AND created_at<? AND event_type IN ('game_view','game_start')"
                    + (gameId == null ? "" : " AND game_id=?");
            Object[] args = gameId == null
                    ? new Object[] {java.sql.Date.valueOf(day), java.sql.Date.valueOf(day.plusDays(1))}
                    : new Object[] {java.sql.Date.valueOf(day), java.sql.Date.valueOf(day.plusDays(1)), gameId};
            Long exact = jdbc.queryForObject(sql, Long.class, args);
            return Map.of("day", day.toString(), "gameId", gameId == null ? "all" : gameId,
                    "uv", exact == null ? 0 : exact, "approximate", false);
        }
    }

    @Scheduled(initialDelay = 60_000, fixedDelay = 3_600_000)
    public void rebuildRecent() {
        LocalDate from = LocalDate.now(ZoneOffset.UTC).minusDays(1);
        List<Map<String, Object>> events = jdbc.query("""
                SELECT game_id,user_id,anonymous_id,created_at FROM play_events
                WHERE created_at>=? AND event_type IN ('game_view','game_start')
                ORDER BY created_at DESC LIMIT 100000
                """, (rs, index) -> Map.<String, Object>of(
                    "game_id", rs.getString("game_id"),
                    "identity", rs.getString("user_id") != null ? "u:" + rs.getString("user_id")
                        : rs.getString("anonymous_id") != null ? "a:" + rs.getString("anonymous_id") : "",
                    "day", rs.getTimestamp("created_at").toInstant().atZone(ZoneOffset.UTC).toLocalDate()
                ), java.sql.Date.valueOf(from));
        for (Map<String, Object> event : events) {
            String identity = (String) event.get("identity");
            if (identity.isEmpty()) continue;
            LocalDate day = (LocalDate) event.get("day");
            try {
                redis.opsForHyperLogLog().add("uv:global:" + day, identity);
                redis.opsForHyperLogLog().add("uv:game:" + event.get("game_id") + ":" + day, identity);
            } catch (RuntimeException unavailable) { return; }
        }
    }
}
