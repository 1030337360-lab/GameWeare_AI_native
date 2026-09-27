package com.gameweare.api.create;

import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * Sweeps per-call usage rows. A pending call older than the sweep window lost its reply
 * (worker crash, dropped provider response or cancelled stream) and is marked unknown so the
 * provider-usage audit trail shows the failure window. This job only surfaces the
 * inconsistency; the provider remains authoritative for quota and billing errors.
 */
@Component
public class AgentUsageReconciliation {
    private static final Logger log = LoggerFactory.getLogger(AgentUsageReconciliation.class);
    private final JdbcTemplate jdbc;

    public AgentUsageReconciliation(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Scheduled(initialDelay = 60000, fixedDelayString = "${gameweare.agent.usage-sweep-interval-ms:300000}")
    public void sweepStalePendingCalls() {
        int stale = jdbc.update(
                "UPDATE agent_model_calls SET state='unknown', ended_at=NOW(6) "
                        + "WHERE state='pending' AND started_at < DATE_SUB(NOW(6), INTERVAL 10 MINUTE)");
        if (stale > 0) {
            List<Map<String, Object>> affected = jdbc.queryForList(
                    "SELECT job_id, COUNT(*) AS unknown_calls FROM agent_model_calls "
                            + "WHERE state='unknown' GROUP BY job_id ORDER BY unknown_calls DESC LIMIT 20");
            log.error("Agent usage reconciliation marked {} stale model calls as unknown; affected jobs: {}",
                    stale, affected.stream().map(row -> row.get("job_id")).toList());
        }
    }
}
