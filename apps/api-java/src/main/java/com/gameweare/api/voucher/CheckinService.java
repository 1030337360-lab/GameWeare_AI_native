package com.gameweare.api.voucher;

import com.gameweare.api.voucher.dao.CheckinMapper;
import java.time.LocalDate;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
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

@Service
class CheckinService {
    private static final ZoneId REWARD_ZONE = ZoneId.of("Asia/Shanghai");
    private final CheckinMapper checkins;
    private final StringRedisTemplate redis;
    private final GenerationVoucherService vouchers;

    CheckinService(CheckinMapper checkins, StringRedisTemplate redis, GenerationVoucherService vouchers) {
        this.checkins = checkins; this.redis = redis; this.vouchers = vouchers;
    }

    @Transactional
    public Map<String, Object> checkin(String userId) {
        LocalDate today = LocalDate.now(REWARD_ZONE);
        checkins.ensureStreak(userId);
        Map<String, Object> state = checkins.lockStreak(userId);
        int inserted = checkins.insertDay(userId, java.sql.Date.valueOf(today));
        if (inserted == 0) return mine(userId);
        LocalDate last = asDay(state.get("last_day"));
        boolean continues = today.minusDays(1).equals(last);
        LocalDate start = continues ? asDay(state.get("streak_start")) : today;
        int streak = continues ? ((Number) state.get("current_streak")).intValue() + 1 : 1;
        checkins.updateStreak(userId, java.sql.Date.valueOf(start), java.sql.Date.valueOf(today), streak);
        int issuedThisMonth = checkins.monthlyAwardCount(userId,
                java.sql.Date.valueOf(today.withDayOfMonth(1)),
                java.sql.Date.valueOf(today.withDayOfMonth(1).plusMonths(1)));
        for (Map<String, Object> rule : effectiveRules()) {
            int milestone = ((Number) rule.get("milestone")).intValue();
            int count = ((Number) rule.get("voucher_count")).intValue();
            Object enabled = rule.get("enabled");
            if (!(enabled instanceof Boolean ? (Boolean) enabled : ((Number) enabled).intValue() != 0)
                    || milestone != streak || issuedThisMonth + count > 2) continue;
            int award = checkins.insertAward(userId, java.sql.Date.valueOf(start),
                    milestone, java.sql.Date.valueOf(today), count);
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
                days = daysInMonth(userId, today);
            }
        } catch (RuntimeException unavailable) {
            days = daysInMonth(userId, today);
        }
        Map<String, Object> state = checkins.state(userId);
        if (state == null) state = Map.of();
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
        List<Map<String, Object>> rows = checkins.leaderboard(java.sql.Date.valueOf(today.minusDays(1)), limit);
        try {
            String key = "checkin:rank:" + today;
            for (Map<String, Object> row : rows)
                redis.opsForZSet().add(key, row.get("userId").toString(), ((Number) row.get("streak")).doubleValue());
            redis.expire(key, java.time.Duration.ofDays(2));
        } catch (RuntimeException ignored) { /* MySQL response remains valid. */ }
        return rows;
    }

    public List<Map<String, Object>> rules() {
        List<Map<String, Object>> rows = checkins.rules();
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
        return checkins.effectiveRules();
    }

    @Transactional
    public List<Map<String, Object>> updateRule(RewardRulesController.Rule rule) {
        if (rule.milestone() < 1 || rule.milestone() > 365 || rule.voucherCount() < 1
                || rule.voucherCount() > 2 || rule.validityDays() < 1 || rule.validityDays() > 365
                || rule.effectiveAt() == null || !rule.effectiveAt().isAfter(Instant.now().plusSeconds(30)))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid reward rule");
        checkins.ensureRule(rule.milestone(), rule.voucherCount(), rule.validityDays());
        checkins.scheduleRule(rule.milestone(),
                java.time.LocalDateTime.ofInstant(rule.effectiveAt(), ZoneOffset.UTC),
                rule.voucherCount(), rule.validityDays(), rule.enabled());
        return rules();
    }

    private List<Integer> daysInMonth(String userId, LocalDate today) {
        return checkins.daysInMonth(userId, java.sql.Date.valueOf(today.withDayOfMonth(1)),
                java.sql.Date.valueOf(today.withDayOfMonth(1).plusMonths(1)));
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
