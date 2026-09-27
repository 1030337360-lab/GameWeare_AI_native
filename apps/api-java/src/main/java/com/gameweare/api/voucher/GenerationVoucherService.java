package com.gameweare.api.voucher;

import java.sql.Date;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class GenerationVoucherService {
    private final JdbcTemplate jdbc;

    public GenerationVoucherService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<Map<String, Object>> mine(String userId) {
        return jdbc.queryForList("""
                SELECT id,source_type AS sourceType,source_id AS sourceId,status,expires_at AS expiresAt,
                       reserved_job_id AS reservedJobId,created_at AS createdAt,used_at AS usedAt
                FROM generation_vouchers WHERE user_id=? ORDER BY created_at DESC LIMIT 100
                """, userId);
    }

    /** Called in the check-in transaction. A source can award each user exactly once. */
    public void grant(String userId, String sourceType, String sourceId, int validityDays) {
        jdbc.update("""
                INSERT IGNORE INTO generation_vouchers(id,user_id,source_type,source_id,status,expires_at)
                VALUES (?,?,?,?,'available',DATE_ADD(UTC_TIMESTAMP(6), INTERVAL ? DAY))
                """, UUID.randomUUID().toString(), userId, sourceType, sourceId, validityDays);
    }

    /** The caller's job insert and this conditional reservation share one MySQL transaction. */
    public void reserve(String userId, String voucherId, String jobId) {
        if (voucherId == null || voucherId.isBlank())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "voucherId is required");
        int changed = jdbc.update("""
                UPDATE generation_vouchers SET status='reserved',reserved_job_id=?
                WHERE id=? AND user_id=? AND status='available' AND expires_at>UTC_TIMESTAMP(6)
                """, jobId, voucherId, userId);
        if (changed != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Voucher is unavailable or expired");
    }

    public void consume(String userId, String jobId) {
        int changed = jdbc.update("""
                UPDATE generation_vouchers SET status='used',used_at=UTC_TIMESTAMP(6)
                WHERE user_id=? AND reserved_job_id=? AND status='reserved'
                """, userId, jobId);
        if (changed != 1) throw new IllegalStateException("Voucher reservation was lost before completion");
    }

    public void release(String userId, String jobId) {
        jdbc.update("""
                UPDATE generation_vouchers
                SET status=IF(expires_at>UTC_TIMESTAMP(6),'available','expired'),reserved_job_id=NULL
                WHERE user_id=? AND reserved_job_id=? AND status='reserved'
                """, userId, jobId);
    }

    @Transactional
    public void expireUnreserved() {
        jdbc.update("UPDATE generation_vouchers SET status='expired' WHERE status='available' AND expires_at<=UTC_TIMESTAMP(6)");
    }

    /** Repair a terminal job whose worker committed before it finalized its voucher. */
    @Scheduled(initialDelay = 10_000, fixedDelay = 60_000)
    @Transactional
    public void reconcileTerminalJobs() {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT v.user_id,v.reserved_job_id,j.status
                FROM generation_vouchers v JOIN create_jobs j ON j.id=v.reserved_job_id
                WHERE v.status='reserved' AND j.status IN ('completed','failed','canceled') LIMIT 100
                """);
        for (Map<String, Object> row : rows) {
            String userId = (String) row.get("user_id");
            String jobId = (String) row.get("reserved_job_id");
            if ("completed".equals(row.get("status"))) consume(userId, jobId);
            else release(userId, jobId);
        }
    }
}
