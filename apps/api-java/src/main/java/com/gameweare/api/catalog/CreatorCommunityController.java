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
