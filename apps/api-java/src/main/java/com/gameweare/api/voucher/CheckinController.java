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

@Service
class CheckinService {
    private static final ZoneId REWARD_ZONE = ZoneId.of("Asia/Shanghai");
    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final GenerationVoucherService vouchers;

    CheckinService(JdbcTemplate jdbc, StringRedisTemplate redis, GenerationVoucherService vouchers) {
        this.jdbc = jdbc; this.redis = redis; this.vouchers = vouchers;
    }

    @Transactional
    public Map<String, Object> checkin(String userId) {
        LocalDate today = LocalDate.now(REWARD_ZONE);
        jdbc.update("INSERT IGNORE INTO checkin_streaks(user_id) VALUES(?)", userId);
        Map<String, Object> state = jdbc.queryForMap(
                "SELECT streak_start,last_day,current_streak FROM checkin_streaks WHERE user_id=? FOR UPDATE", userId);
        int inserted = jdbc.update("INSERT IGNORE INTO daily_checkins(user_id,checkin_day) VALUES(?,?)",
                userId, java.sql.Date.valueOf(today));
        if (inserted == 0) return mine(userId);
        LocalDate last = asDay(state.get("last_day"));
        boolean continues = today.minusDays(1).equals(last);
        LocalDate start = continues ? asDay(state.get("streak_start")) : today;
        int streak = continues ? ((Number) state.get("current_streak")).intValue() + 1 : 1;
        jdbc.update("""
                UPDATE checkin_streaks SET streak_start=?,last_day=?,current_streak=?,
                    longest_streak=GREATEST(longest_streak,?),total_days=total_days+1 WHERE user_id=?
                """, java.sql.Date.valueOf(start), java.sql.Date.valueOf(today), streak, streak, userId);
        int issuedThisMonth = jdbc.queryForObject("""
                SELECT COALESCE(SUM(awarded_count),0) FROM checkin_awards WHERE user_id=?
                AND award_day>=? AND award_day<?
                """, Integer.class, userId, java.sql.Date.valueOf(today.withDayOfMonth(1)),
                java.sql.Date.valueOf(today.withDayOfMonth(1).plusMonths(1)));
        for (Map<String, Object> rule : effectiveRules()) {
            int milestone = ((Number) rule.get("milestone")).intValue();
            int count = ((Number) rule.get("voucher_count")).intValue();
            Object enabled = rule.get("enabled");
            if (!(enabled instanceof Boolean ? (Boolean) enabled : ((Number) enabled).intValue() != 0)
                    || milestone != streak || issuedThisMonth + count > 2) continue;
            int award = jdbc.update("INSERT IGNORE INTO checkin_awards(user_id,streak_start,milestone,award_day,awarded_count) VALUES(?,?,?,?,?)",
                    userId, java.sql.Date.valueOf(start), milestone, java.sql.Date.valueOf(today), count);
            if (award == 1) for (int n = 0; n < count; n++) {
                vouchers.grant(userId, "checkin", start + ":" + milestone + ":" + n,
                        ((Number) rule.get("validity_days")).intValue());
                issuedThisMonth++;
            }
        }
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() { project(userId, today, streak); }
        });
        Map<String, Object> result = new java.util.LinkedHashMap<>(mine(userId));
        @SuppressWarnings("unchecked") List<Integer> displayed = new ArrayList<>((List<Integer>) result.get("days"));
        if (!displayed.contains(today.getDayOfMonth())) displayed.add(today.getDayOfMonth());
        result.put("days", displayed);
        result.put("currentStreak", streak);
        return result;
    }

    public Map<String, Object> mine(String userId) {
        LocalDate today = LocalDate.now(REWARD_ZONE);
        List<Integer> days = new ArrayList<>();
        String key = bitmapKey(userId, today);
        try {
            if (Boolean.TRUE.equals(redis.hasKey(key))) {
                for (int d = 1; d <= today.lengthOfMonth(); d++)
                    if (Boolean.TRUE.equals(redis.opsForValue().getBit(key, d - 1))) days.add(d);
            } else {
                days = jdbc.queryForList("SELECT DAY(checkin_day) FROM daily_checkins WHERE user_id=? AND checkin_day>=? AND checkin_day<? ORDER BY checkin_day",
                        Integer.class, userId, java.sql.Date.valueOf(today.withDayOfMonth(1)),
                        java.sql.Date.valueOf(today.withDayOfMonth(1).plusMonths(1)));
            }
        } catch (RuntimeException unavailable) {
            days = jdbc.queryForList("SELECT DAY(checkin_day) FROM daily_checkins WHERE user_id=? AND checkin_day>=? AND checkin_day<? ORDER BY checkin_day",
                    Integer.class, userId, java.sql.Date.valueOf(today.withDayOfMonth(1)),
                    java.sql.Date.valueOf(today.withDayOfMonth(1).plusMonths(1)));
        }
        List<Map<String, Object>> states = jdbc.queryForList(
                "SELECT last_day,current_streak,longest_streak,total_days FROM checkin_streaks WHERE user_id=?", userId);
        Map<String, Object> state = states.isEmpty() ? Map.of() : states.get(0);
        int current = state.isEmpty() || state.get("last_day") == null ? 0
                : asDay(state.get("last_day")).isBefore(today.minusDays(1)) ? 0
                : ((Number) state.get("current_streak")).intValue();
        return Map.of("month", today.toString().substring(0, 7), "days", days,
                "currentStreak", current,
                "longestStreak", state.isEmpty() ? 0 : state.get("longest_streak"),
                "totalDays", state.isEmpty() ? 0 : state.get("total_days"));
    }

    public List<Map<String, Object>> leaderboard(int limit) {
        LocalDate today = LocalDate.now(REWARD_ZONE);
        // MySQL remains authoritative; this query also removes stale scores after missed days.
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT s.user_id AS userId,u.display_name AS displayName,s.current_streak AS streak
                FROM checkin_streaks s JOIN users u ON u.id=s.user_id
                WHERE s.last_day>=? ORDER BY s.current_streak DESC,s.last_day ASC,s.user_id ASC LIMIT ?
                """, java.sql.Date.valueOf(today.minusDays(1)), limit);
        try {
            String key = "checkin:rank:" + today;
            for (Map<String, Object> row : rows)
                redis.opsForZSet().add(key, row.get("userId").toString(), ((Number) row.get("streak")).doubleValue());
            redis.expire(key, java.time.Duration.ofDays(2));
        } catch (RuntimeException ignored) { /* MySQL response remains valid. */ }
        return rows;
    }

    public List<Map<String, Object>> rules() {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT milestone,voucher_count AS voucherCount,validity_days AS validityDays,enabled,
                       NULL AS effectiveAt,'active' AS state FROM checkin_reward_rules
                UNION ALL
                SELECT milestone,voucher_count AS voucherCount,validity_days AS validityDays,enabled,
                       effective_at AS effectiveAt,'scheduled' AS state
                FROM checkin_reward_rule_changes WHERE effective_at>UTC_TIMESTAMP(6)
                ORDER BY milestone,effectiveAt
                """);
        for (Map<String, Object> row : rows) {
            Object effectiveAt = row.get("effectiveAt");
            if (effectiveAt instanceof java.time.LocalDateTime dateTime)
                row.put("effectiveAt", dateTime.toInstant(ZoneOffset.UTC));
            else if (effectiveAt instanceof java.sql.Timestamp timestamp)
                row.put("effectiveAt", timestamp.toLocalDateTime().toInstant(ZoneOffset.UTC));
        }
        return rows;
    }

    private List<Map<String, Object>> effectiveRules() {
        return jdbc.queryForList("""
                SELECT base.milestone,
                       COALESCE(change_rule.voucher_count,base.voucher_count) AS voucher_count,
                       COALESCE(change_rule.validity_days,base.validity_days) AS validity_days,
                       COALESCE(change_rule.enabled,base.enabled) AS enabled
                FROM checkin_reward_rules base
                LEFT JOIN checkin_reward_rule_changes change_rule
                  ON change_rule.milestone=base.milestone
                 AND change_rule.effective_at=(SELECT MAX(c.effective_at)
                      FROM checkin_reward_rule_changes c
                      WHERE c.milestone=base.milestone AND c.effective_at<=UTC_TIMESTAMP(6))
                ORDER BY base.milestone
                """);
    }

    @Transactional
    public List<Map<String, Object>> updateRule(RewardRulesController.Rule rule) {
        if (rule.milestone() < 1 || rule.milestone() > 365 || rule.voucherCount() < 1
                || rule.voucherCount() > 2 || rule.validityDays() < 1 || rule.validityDays() > 365
                || rule.effectiveAt() == null || !rule.effectiveAt().isAfter(Instant.now().plusSeconds(30)))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid reward rule");
        jdbc.update("INSERT IGNORE INTO checkin_reward_rules(milestone,voucher_count,validity_days,enabled) VALUES(?,?,?,FALSE)",
                rule.milestone(), rule.voucherCount(), rule.validityDays());
        jdbc.update("""
                INSERT INTO checkin_reward_rule_changes(milestone,effective_at,voucher_count,validity_days,enabled)
                VALUES(?,?,?,?,?)
                """, rule.milestone(), java.time.LocalDateTime.ofInstant(rule.effectiveAt(), ZoneOffset.UTC),
                rule.voucherCount(), rule.validityDays(), rule.enabled());
        return rules();
    }

    private void project(String userId, LocalDate day, int streak) {
        try {
            redis.opsForValue().setBit(bitmapKey(userId, day), day.getDayOfMonth() - 1, true);
            redis.expire(bitmapKey(userId, day), java.time.Duration.ofDays(400));
            redis.opsForZSet().add("checkin:rank:" + day, userId, streak);
        } catch (RuntimeException ignored) { /* Durable MySQL records can rebuild the projection. */ }
    }

    private String bitmapKey(String userId, LocalDate day) {
        return "checkin:bitmap:" + userId + ":" + day.toString().substring(0, 7);
    }

    private static LocalDate asDay(Object value) {
        if (value == null) return null;
        if (value instanceof LocalDate day) return day;
        if (value instanceof java.sql.Date day) return day.toLocalDate();
        if (value instanceof java.time.LocalDateTime dateTime) return dateTime.toLocalDate();
        throw new IllegalStateException("Unexpected check-in date type: " + value);
    }

    @Scheduled(cron = "0 5 0 * * *", zone = "UTC")
    public void expireVouchers() { vouchers.expireUnreserved(); }
}
