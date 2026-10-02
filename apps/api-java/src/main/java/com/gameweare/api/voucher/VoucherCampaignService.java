package com.gameweare.api.voucher;

import com.gameweare.api.voucher.dao.VoucherCampaignMapper;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class VoucherCampaignService {
    static final String STREAM = "voucher:seckill:events";
    private static final DefaultRedisScript<String> RESERVE = script("voucher-reserve.lua", String.class);
    private static final DefaultRedisScript<Long> COMPENSATE = script("voucher-compensate.lua", Long.class);
    private final VoucherCampaignMapper campaigns;
    private final StringRedisTemplate redis;
    private final GenerationVoucherService vouchers;
    private final TransactionTemplate transactions;
    private final VoucherStageMetrics metrics;

    public VoucherCampaignService(VoucherCampaignMapper campaigns, StringRedisTemplate redis, GenerationVoucherService vouchers,
                                  PlatformTransactionManager manager, VoucherStageMetrics metrics) {
        this.campaigns = campaigns; this.redis = redis; this.vouchers = vouchers;
        this.transactions = new TransactionTemplate(manager);
        this.metrics = metrics;
    }

    private static <T> DefaultRedisScript<T> script(String path, Class<T> resultType) {
        DefaultRedisScript<T> script = new DefaultRedisScript<>();
        script.setLocation(new ClassPathResource(path));
        script.setResultType(resultType);
        return script;
    }

    public List<Map<String, Object>> list() {
        return campaigns.list().stream().map(row -> Map.<String, Object>of(
                "id", row.get("id"), "title", row.get("title"),
                "startsAt", asInstant(row.get("starts_at")),
                "endsAt", asInstant(row.get("ends_at")),
                "totalStock", row.get("total_stock"),
                "remainingStock", row.get("remaining_stock"),
                "status", row.get("status"))).toList();
    }

    @Transactional
    public Map<String, Object> create(VoucherCampaignMaintenanceController.NewCampaign input) {
        if (input.title() == null || input.title().isBlank() || input.title().length() > 160
                || input.startsAt() == null || input.endsAt() == null
                || !input.startsAt().isBefore(input.endsAt()) || input.stock() < 1 || input.stock() > 1_000_000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid voucher campaign");
        if (!input.startsAt().isAfter(Instant.now().plusSeconds(30)))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Campaign must start at least 30 seconds from now");
        String id = UUID.randomUUID().toString();
        campaigns.insertCampaign(id, input.title().trim(),
                LocalDateTime.ofInstant(input.startsAt(), ZoneOffset.UTC),
                LocalDateTime.ofInstant(input.endsAt(), ZoneOffset.UTC), input.stock());
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() {
                try { redis.opsForValue().setIfAbsent(stockKey(id), Integer.toString(input.stock())); }
                catch (RuntimeException ignored) { /* Missing Redis stock fails claims closed until repaired. */ }
            }
        });
        return Map.of("id", id, "title", input.title().trim(), "totalStock", input.stock(),
                "startsAt", input.startsAt(), "endsAt", input.endsAt());
    }

    public Map<String, Object> claim(String campaignId, String userId) {
        Map<String, Object> campaign = metrics.time("claim.mysql_campaign_read", () -> campaigns.campaign(campaignId));
        if (campaign == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Campaign not found");
        if ("canceled".equals(campaign.get("status")))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Campaign canceled");
        String reservationId = UUID.randomUUID().toString();
        String response;
        try {
            response = metrics.time("claim.redis_reserve_lua", () -> redis.execute(RESERVE,
                    List.of(stockKey(campaignId), usersKey(campaignId), stateKey(reservationId), STREAM,
                            ownerKey(reservationId)),
                    campaignId, userId, reservationId,
                    Long.toString(asInstant(campaign.get("starts_at")).toEpochMilli()),
                    Long.toString(asInstant(campaign.get("ends_at")).toEpochMilli())));
        } catch (RuntimeException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Seckill temporarily unavailable", unavailable);
        }
        if (response == null || "UNAVAILABLE".equals(response))
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Campaign stock is not ready");
        if ("NOT_STARTED".equals(response) || "ENDED".equals(response))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Campaign is not active");
        if ("SOLD_OUT".equals(response))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Voucher campaign is sold out");
        if (response.startsWith("DUP:")) return result(campaignId, response.substring(4), "pending", null);
        if (!response.startsWith("OK:")) throw new IllegalStateException("Unexpected seckill result");
        return result(campaignId, reservationId, "pending", Integer.parseInt(response.substring(3)));
    }

    public Map<String, Object> mine(String campaignId, String userId) {
        Map<String, Object> row = campaigns.claimByUser(campaignId, userId);
        if (row != null) {
            Map<String, Object> result = new java.util.LinkedHashMap<>();
            result.put("campaignId", campaignId);
            result.put("reservationId", row.get("reservationId"));
            result.put("status", row.get("status"));
            result.put("voucherId", row.get("voucherId"));
            return result;
        }
        String id;
        try { id = (String) redis.opsForHash().get(usersKey(campaignId), userId); }
        catch (RuntimeException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Claim status temporarily unavailable", unavailable);
        }
        if (id == null) return Map.of("campaignId", campaignId, "status", "none");
        String status = redis.opsForValue().get(stateKey(id));
        return result(campaignId, id, status == null ? "pending" : status.startsWith("pending") ? "pending" : status, null);
    }

    /** A failed reservation remains queryable after its user pre-hold is released. */
    public Map<String, Object> reservation(String campaignId, String userId, String reservationId) {
        if (campaigns.ownedReservationCount(reservationId, campaignId, userId) > 0)
            return mine(campaignId, userId);
        String owner;
        String status;
        try {
            owner = redis.opsForValue().get(ownerKey(reservationId));
            status = redis.opsForValue().get(stateKey(reservationId));
        } catch (RuntimeException unavailable) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,
                    "Claim status temporarily unavailable", unavailable);
        }
        if (!(campaignId + "|" + userId).equals(owner) || status == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Reservation not found");
        return result(campaignId, reservationId,
                status.startsWith("pending") ? "pending" : status, null);
    }

    private Map<String, Object> result(String campaignId, String reservationId, String status, Integer remaining) {
        if (remaining == null)
            return Map.of("campaignId", campaignId, "reservationId", reservationId, "status", status);
        return Map.of("campaignId", campaignId, "reservationId", reservationId, "status", status,
                "remainingAfter", remaining);
    }

    /** Called only by the Rabbit listener. MySQL is the final stock and ownership authority. */
    @Transactional
    public boolean issue(String campaignId, String userId, String reservationId, int remainingAfter) {
        // Serialize issuance and terminal compensation for this campaign in MySQL.
        metrics.time("consumer.mysql_campaign_lock", () -> campaigns.lockStock(campaignId));
        if (campaigns.claimCountById(reservationId) > 0) { projectIssued(reservationId); return false; }
        String state = metrics.time("consumer.redis_reservation_check",
                () -> redis.opsForValue().get(stateKey(reservationId)));
        if (state == null || !state.startsWith("pending")
                || !reservationId.equals(redis.opsForHash().get(usersKey(campaignId), userId)))
            throw new IllegalStateException("Reservation is no longer pending");
        if (campaigns.claimCountByUser(campaignId, userId) > 0)
            throw new IllegalStateException("User already claimed this campaign");
        int stock = campaigns.decrementStock(campaignId);
        if (stock != 1) throw new IllegalStateException("MySQL campaign stock exhausted");
        campaigns.insertClaim(reservationId, campaignId, userId, remainingAfter);
        vouchers.grant(userId, "campaign", campaignId, 30);
        projectIssued(reservationId);
        return true;
    }

    private void projectIssued(String reservationId) {
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override public void afterCommit() {
                try { redis.opsForValue().set(stateKey(reservationId), "issued", java.time.Duration.ofDays(45)); }
                catch (RuntimeException ignored) { /* MySQL remains authoritative. */ }
            }
        });
    }

    @Transactional
    public void compensate(String campaignId, String userId, String reservationId) {
        campaigns.lockStock(campaignId);
        if (campaigns.claimCountById(reservationId) > 0) return;
        redis.execute(COMPENSATE, List.of(stockKey(campaignId), usersKey(campaignId), stateKey(reservationId)),
                userId, reservationId);
    }

    public Map<String, Object> reconcile(String campaignId) {
        Map<String, Object> row = campaigns.reconcile(campaignId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Campaign not found");
        String redisStock;
        Long reservations;
        try {
            redisStock = redis.opsForValue().get(stockKey(campaignId));
            reservations = redis.opsForHash().size(usersKey(campaignId));
        } catch (RuntimeException unavailable) { redisStock = null; reservations = null; }
        long issued = ((Number) row.get("issuedCount")).longValue();
        long remaining = ((Number) row.get("remainingStock")).longValue();
        long total = ((Number) row.get("totalStock")).longValue();
        Map<String, Object> report = new java.util.LinkedHashMap<>();
        report.put("campaignId", campaignId);
        report.put("totalStock", total);
        report.put("remainingStock", remaining);
        report.put("issuedCount", issued);
        report.put("mysqlBalanced", issued + remaining == total);
        report.put("redisStock", redisStock == null ? "unavailable" : redisStock);
        report.put("provisionalReservations", reservations == null ? "unavailable" : Math.max(0, reservations - issued));
        return report;
    }

    /** Sweep old provisional reservations after normal Rabbit retries had time to finish. */
    @Scheduled(fixedDelayString = "${gameweare.voucher.reconcile-ms:300000}")
    public void reconcileStaleReservations() {
        List<String> ids = campaigns.recentCampaignIds();
        long cutoff = Instant.now().minusSeconds(600).toEpochMilli();
        for (String campaignId : ids) {
            try (var entries = redis.opsForHash().scan(usersKey(campaignId), ScanOptions.scanOptions().count(100).build())) {
                int inspected = 0;
                while (entries.hasNext() && inspected++ < 500) {
                    var entry = entries.next();
                    String userId = entry.getKey().toString();
                    String reservationId = entry.getValue().toString();
                    String state = redis.opsForValue().get(stateKey(reservationId));
                    if (state == null || !state.startsWith("pending:")) continue;
                    long created = Long.parseLong(state.substring(8));
                    if (created < cutoff) transactions.executeWithoutResult(
                            status -> compensate(campaignId, userId, reservationId));
                }
            } catch (RuntimeException unavailable) {
                // Stop this pass; a later pass can still settle Redis and MySQL after recovery.
            }
        }
    }

    static String stockKey(String id) { return "voucher:campaign:" + id + ":stock"; }
    static String ownerKey(String id) { return "voucher:reservation:" + id + ":owner"; }
    private static Instant asInstant(Object value) {
        if (value instanceof java.sql.Timestamp timestamp) return timestamp.toLocalDateTime().toInstant(ZoneOffset.UTC);
        if (value instanceof LocalDateTime dateTime) return dateTime.toInstant(ZoneOffset.UTC);
        throw new IllegalStateException("Unexpected campaign time type: " + value);
    }
    static String usersKey(String id) { return "voucher:campaign:" + id + ":users"; }
    static String stateKey(String id) { return "voucher:reservation:" + id; }
}
