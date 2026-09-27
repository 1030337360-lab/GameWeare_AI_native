package com.gameweare.api.create;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** The sweep must only surface the billing failure window, never edit balances. */
class AgentUsageReconciliationTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final AgentUsageReconciliation sweep = new AgentUsageReconciliation(db);

    @Test
    void stalePendingCallsAreMarkedUnknownAndAggregatedPerJob() {
        when(db.update(contains("state='unknown'"))).thenReturn(3);
        when(db.queryForList(contains("GROUP BY job_id"))).thenReturn(List.of(
                Map.of("job_id", "job-1", "unknown_calls", 3L)));

        sweep.sweepStalePendingCalls();

        verify(db).update("UPDATE agent_model_calls SET state='unknown', ended_at=NOW(6) "
                + "WHERE state='pending' AND started_at < DATE_SUB(NOW(6), INTERVAL 10 MINUTE)");
        verify(db).queryForList(contains("GROUP BY job_id"));
    }

    @Test
    void cleanSweepRunsNoJobAggregation() {
        when(db.update(anyString())).thenReturn(0);

        sweep.sweepStalePendingCalls();

        verify(db).update(contains("state='pending'"));
        verify(db, never()).queryForList(anyString());
    }
}
