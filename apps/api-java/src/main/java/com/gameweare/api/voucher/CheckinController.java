package com.gameweare.api.voucher;

import java.time.LocalDate;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/checkins")
public class CheckinController {
    private final CheckinService service;
    public CheckinController(CheckinService service) { this.service = service; }

    @PostMapping
    public Map<String, Object> checkin(@RequestAttribute("userId") String userId) { return service.checkin(userId); }

    @GetMapping("/me")
    public Map<String, Object> mine(@RequestAttribute("userId") String userId) { return service.mine(userId); }

    @GetMapping("/leaderboard")
    public List<Map<String, Object>> leaderboard(@RequestParam(defaultValue = "20") int limit) {
        return service.leaderboard(Math.max(1, Math.min(limit, 100)));
    }
}

@RestController
@RequestMapping("/maintenance/reward-rules")
class RewardRulesController {
    private final CheckinService service;
    RewardRulesController(CheckinService service) { this.service = service; }
    record Rule(int milestone, int voucherCount, int validityDays, boolean enabled, Instant effectiveAt) {}

    @GetMapping
    public List<Map<String, Object>> list() { return service.rules(); }

    @PutMapping
    public List<Map<String, Object>> update(@RequestBody Rule rule) { return service.updateRule(rule); }
}
