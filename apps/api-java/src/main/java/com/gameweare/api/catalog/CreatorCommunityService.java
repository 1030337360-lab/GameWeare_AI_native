package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.CreatorCommunityMapper;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
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

@Service
class CreatorCommunityService {
    private final CreatorCommunityMapper creators;
    private final StringRedisTemplate redis;
    CreatorCommunityService(CreatorCommunityMapper creators, StringRedisTemplate redis) {
        this.creators = creators; this.redis = redis;
    }

    public Map<String, Object> profile(String id) {
        Map<String, Object> row = creators.profile(id);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Creator not found");
        return row;
    }

    public boolean isFollowing(String userId, String creatorId) {
        return creators.followCount(userId, creatorId) > 0;
    }

    @Transactional
    public Map<String, Object> follow(String userId, String creatorId, boolean enabled) {
        if (userId.equals(creatorId)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot follow yourself");
        profile(creatorId);
        if (enabled) creators.follow(userId, creatorId);
        else creators.unfollow(userId, creatorId);
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
                return ids.stream().limit(50).map(creators::publicCreator)
                        .filter(java.util.Objects::nonNull).toList();
            }
            return List.of();
        } catch (RuntimeException unavailable) {
            return creators.common(userId, otherId);
        }
    }

    public List<Map<String, Object>> feed(String userId, int limit) {
        return creators.feed(userId, limit);
    }

    private void populate(String userId) {
        if (Boolean.TRUE.equals(redis.hasKey(readyKey(userId)))) return;
        List<String> ids = creators.followingIds(userId);
        if (!ids.isEmpty()) redis.opsForSet().add(followsKey(userId), ids.toArray(String[]::new));
        redis.opsForValue().set(readyKey(userId), "1", Duration.ofHours(1));
        redis.expire(followsKey(userId), Duration.ofHours(1));
    }
    private String followsKey(String userId) { return "creator:following:" + userId; }
    private String readyKey(String userId) { return "creator:following:ready:" + userId; }
}
