package com.gameweare.api.billing;

import com.gameweare.api.billing.dao.TokenAccountMapper;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/** Read-only audit: financial discrepancies require investigation rather than automatic balance edits. */
@Component
public class TokenReconciliation {
    private static final Logger log = LoggerFactory.getLogger(TokenReconciliation.class);
    private final TokenAccountMapper accounts;

    public TokenReconciliation(TokenAccountMapper accounts) { this.accounts = accounts; }

    @Scheduled(initialDelay = 30000, fixedDelayString = "${gameweare.billing.reconcile-interval-ms:3600000}")
    public void auditAccounts() {
        List<Map<String, Object>> mismatches = accounts.accountMismatches();
        if (!mismatches.isEmpty()) {
            log.error("Token ledger reconciliation found {} mismatched accounts; first user ID: {}",
                    mismatches.size(), mismatches.get(0).get("user_id"));
        }
    }
}
