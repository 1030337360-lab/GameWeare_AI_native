package com.gameweare.api.voucher;

import com.gameweare.api.voucher.dao.GenerationVoucherMapper;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class GenerationVoucherService {
    private final GenerationVoucherMapper vouchers;

    public GenerationVoucherService(GenerationVoucherMapper vouchers) { this.vouchers = vouchers; }

    public List<Map<String, Object>> mine(String userId) {
        return vouchers.mine(userId);
    }

    /** Called in the check-in transaction. A source can award each user exactly once. */
    public void grant(String userId, String sourceType, String sourceId, int validityDays) {
        vouchers.grant(UUID.randomUUID().toString(), userId, sourceType, sourceId, validityDays);
    }

    /** The caller's job insert and this conditional reservation share one MySQL transaction. */
    public void reserve(String userId, String voucherId, String jobId) {
        if (voucherId == null || voucherId.isBlank())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "voucherId is required");
        int changed = vouchers.reserve(userId, voucherId, jobId);
        if (changed != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Voucher is unavailable or expired");
    }

    public void consume(String userId, String jobId) {
        int changed = vouchers.consume(userId, jobId);
        if (changed != 1) throw new IllegalStateException("Voucher reservation was lost before completion");
    }

    public void release(String userId, String jobId) {
        vouchers.release(userId, jobId);
    }

    @Transactional
    public void expireUnreserved() {
        vouchers.expireUnreserved();
    }

    /** Repair a terminal job whose worker committed before it finalized its voucher. */
    @Scheduled(initialDelay = 10_000, fixedDelay = 60_000)
    @Transactional
    public void reconcileTerminalJobs() {
        List<Map<String, Object>> rows = vouchers.terminalReservations();
        for (Map<String, Object> row : rows) {
            String userId = (String) row.get("user_id");
            String jobId = (String) row.get("reserved_job_id");
            if ("completed".equals(row.get("status"))) consume(userId, jobId);
            else release(userId, jobId);
        }
    }
}
