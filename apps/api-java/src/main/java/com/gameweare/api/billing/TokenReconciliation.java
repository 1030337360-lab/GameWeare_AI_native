package com.gameweare.api.billing;

import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Read-only audit: financial discrepancies require investigation rather than automatic balance edits. */
@Component
public class TokenReconciliation {
    private static final Logger log = LoggerFactory.getLogger(TokenReconciliation.class);
    private final JdbcTemplate jdbc;

    public TokenReconciliation(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @Scheduled(initialDelay = 30000, fixedDelayString = "${yahaha.billing.reconcile-interval-ms:3600000}")
    public void auditAccounts() {
        List<Map<String, Object>> mismatches = jdbc.queryForList("""
                SELECT a.user_id, a.balance, a.reserved,
                       COALESCE(SUM(CASE l.entry_type
                           WHEN 'GRANT' THEN l.amount
                           WHEN 'RESERVE' THEN -l.amount
                           WHEN 'REFUND' THEN l.amount ELSE 0 END), 0) AS expected_balance,
                       COALESCE(SUM(CASE l.entry_type
                           WHEN 'RESERVE' THEN l.amount
                           WHEN 'SETTLE' THEN -l.amount
                           WHEN 'REFUND' THEN -l.amount ELSE 0 END), 0) AS expected_reserved
                FROM token_accounts a LEFT JOIN token_ledger l ON l.user_id=a.user_id
                GROUP BY a.user_id, a.balance, a.reserved
                HAVING a.balance < 0 OR a.reserved < 0
                    OR a.balance <> expected_balance OR a.reserved <> expected_reserved
                LIMIT 100
                """);
        if (!mismatches.isEmpty()) {
            log.error("Token ledger reconciliation found {} mismatched accounts; first user ID: {}",
                    mismatches.size(), mismatches.get(0).get("user_id"));
        }
    }
}
