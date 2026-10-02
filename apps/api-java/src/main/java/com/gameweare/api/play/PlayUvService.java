package com.gameweare.api.play;

import com.gameweare.api.play.dao.PlayUvMapper;
import com.gameweare.api.play.entity.PlayIdentityEvent;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
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
    private final PlayUvMapper events;
    private final StringRedisTemplate redis;
    public PlayUvService(PlayUvMapper events, StringRedisTemplate redis) { this.events = events; this.redis = redis; }

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
            Long exact = events.exactUv(java.sql.Date.valueOf(day),
                    java.sql.Date.valueOf(day.plusDays(1)), gameId);
            return Map.of("day", day.toString(), "gameId", gameId == null ? "all" : gameId,
                    "uv", exact == null ? 0 : exact, "approximate", false);
        }
    }

    @Scheduled(initialDelay = 60_000, fixedDelay = 3_600_000)
    public void rebuildRecent() {
        LocalDate from = LocalDate.now(ZoneOffset.UTC).minusDays(1);
        for (PlayIdentityEvent event : events.recentEvents(java.sql.Date.valueOf(from))) {
            String identity = event.userId() != null ? "u:" + event.userId()
                    : event.anonymousId() != null ? "a:" + event.anonymousId() : "";
            if (identity.isEmpty()) continue;
            LocalDate day = event.createdAt().toInstant().atZone(ZoneOffset.UTC).toLocalDate();
            try {
                redis.opsForHyperLogLog().add("uv:global:" + day, identity);
                redis.opsForHyperLogLog().add("uv:game:" + event.gameId() + ":" + day, identity);
            } catch (RuntimeException unavailable) { return; }
        }
    }
}
