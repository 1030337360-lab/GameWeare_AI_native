package com.gameweare.api.catalog;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/creators")
public class CreatorCommunityController {
    private final CreatorCommunityService community;
    public CreatorCommunityController(CreatorCommunityService community) { this.community = community; }
    @GetMapping("/{id}")
    public Map<String, Object> profile(@PathVariable String id) { return community.profile(id); }
    @GetMapping("/{id}/following/me")
    public Map<String, Object> following(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return Map.of("following", community.isFollowing(userId, id));
    }
    @PutMapping("/{id}/follow")
    public Map<String, Object> follow(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return community.follow(userId, id, true);
    }
    @DeleteMapping("/{id}/follow")
    public Map<String, Object> unfollow(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return community.follow(userId, id, false);
    }
    @GetMapping("/{id}/following/common")
    public List<Map<String, Object>> common(@PathVariable String id, @RequestAttribute("userId") String userId) {
        return community.common(userId, id);
    }
}

@RestController
@RequestMapping("/feed/following")
class FollowingFeedController {
    private final CreatorCommunityService community;
    FollowingFeedController(CreatorCommunityService community) { this.community = community; }
    @GetMapping
    public List<Map<String, Object>> feed(@RequestAttribute("userId") String userId,
                                          @RequestParam(defaultValue = "20") int limit) {
        return community.feed(userId, Math.max(1, Math.min(limit, 50)));
    }
}

@Service
class CreatorCommunityService {
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    CreatorCommunityService(JdbcTemplate jdbc, StringRedisTemplate redis) { this.jdbc = jdbc; this.redis = redis; }

    public Map<String, Object> profile(String id) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT u.id,u.display_name AS displayName,u.avatar_url AS avatarUrl,
                       (SELECT COUNT(*) FROM creator_follows f WHERE f.creator_id=u.id) AS followers
                FROM users u WHERE u.id=? AND EXISTS(
                    SELECT 1 FROM games g WHERE g.author_id=u.id AND g.publish_status='published' AND g.visibility='public')
                """, id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Creator not found");
        return rows.get(0);
    }

    public boolean isFollowing(String userId, String creatorId) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM creator_follows WHERE user_id=? AND creator_id=?",
                Integer.class, userId, creatorId);
        return count != null && count > 0;
    }

    @Transactional
    public Map<String, Object> follow(String userId, String creatorId, boolean enabled) {
        if (userId.equals(creatorId)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot follow yourself");
        profile(creatorId);
        if (enabled) jdbc.update("INSERT IGNORE INTO creator_follows(user_id,creator_id) VALUES(?,?)", userId, creatorId);
        else jdbc.update("DELETE FROM creator_follows WHERE user_id=? AND creator_id=?", userId, creatorId);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() {
                try {
                    redis.delete(followsKey(userId));
                    redis.delete(readyKey(userId));
                } catch (RuntimeException ignored) { /* SQL is authoritative. */ }
            }
        });
        return Map.of("creatorId", creatorId, "following", enabled);
    }

    public List<Map<String, Object>> common(String userId, String otherId) {
        profile(otherId);
        try {
            populate(userId); populate(otherId);
            Set<String> ids = redis.opsForSet().intersect(followsKey(userId), followsKey(otherId));
            if (ids != null && !ids.isEmpty()) {
                return ids.stream().limit(50).flatMap(id -> jdbc.queryForList(
                        "SELECT id,display_name AS displayName,avatar_url AS avatarUrl FROM users u WHERE u.id=? AND EXISTS (SELECT 1 FROM games g WHERE g.author_id=u.id AND g.publish_status='published' AND g.visibility='public')", id)
                        .stream()).toList();
            }
            return List.of();
        } catch (RuntimeException unavailable) {
            return jdbc.queryForList("""
                    SELECT u.id,u.display_name AS displayName,u.avatar_url AS avatarUrl
                    FROM creator_follows a JOIN creator_follows b ON b.creator_id=a.creator_id
                    JOIN users u ON u.id=a.creator_id
                    WHERE a.user_id=? AND b.user_id=? AND EXISTS
                      (SELECT 1 FROM games g WHERE g.author_id=u.id AND g.publish_status='published' AND g.visibility='public')
                    LIMIT 50
                    """, userId, otherId);
        }
    }

    public List<Map<String, Object>> feed(String userId, int limit) {
        return jdbc.queryForList("""
                SELECT g.slug AS id,g.title,g.description,g.published_at AS publishedAt,
                       u.id AS creatorId,u.display_name AS creatorName,g.plays_count AS plays,
                       g.likes_count AS likes
                FROM creator_follows f JOIN games g ON g.author_id=f.creator_id
                JOIN users u ON u.id=f.creator_id
                WHERE f.user_id=? AND g.publish_status='published' AND g.visibility='public'
                ORDER BY g.published_at DESC,g.id DESC LIMIT ?
                """, userId, limit);
    }

    private void populate(String userId) {
        if (Boolean.TRUE.equals(redis.hasKey(readyKey(userId)))) return;
        List<String> ids = jdbc.queryForList("SELECT creator_id FROM creator_follows WHERE user_id=?", String.class, userId);
        if (!ids.isEmpty()) redis.opsForSet().add(followsKey(userId), ids.toArray(String[]::new));
        redis.opsForValue().set(readyKey(userId), "1", Duration.ofHours(1));
        redis.expire(followsKey(userId), Duration.ofHours(1));
    }
    private String followsKey(String userId) { return "creator:following:" + userId; }
    private String readyKey(String userId) { return "creator:following:ready:" + userId; }
}
