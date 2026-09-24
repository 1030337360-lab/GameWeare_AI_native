package com.gameweare.api.config;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Outbox delivery: atomic claim, retry with backoff, stale-send recovery. */
class OutboxPublisherTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final RabbitTemplate rabbit = mock(RabbitTemplate.class);
    private final OutboxPublisher publisher = new OutboxPublisher(jdbc, rabbit);

    private void pendingEvent() {
        when(jdbc.queryForList(anyString()))
                .thenReturn(List.of(Map.<String, Object>of("id", "e1", "aggregate_id", "job-1")));
    }

    @Test
    void eventClaimedByAnotherPublisherIsSkipped() {
        pendingEvent();
        when(jdbc.update(contains("status='sending'"), eq("e1"))).thenReturn(0);

        publisher.publishPending();

        verify(rabbit, never()).convertAndSend(anyString(), anyString(), any(Object.class), any(CorrelationData.class));
        verify(jdbc, never()).update(contains("status='sent'"), any(Object[].class));
    }

    @Test
    void brokerFailureRequeuesEventWithBackoff() {
        pendingEvent();
        when(jdbc.update(contains("status='sending'"), eq("e1"))).thenReturn(1);
        doThrow(new RuntimeException("broker unreachable"))
                .when(rabbit).convertAndSend(anyString(), anyString(), any(Object.class), any(CorrelationData.class));

        publisher.publishPending();

        verify(rabbit).convertAndSend(eq(InfrastructureConfig.CREATE_EXCHANGE), eq("job.created"),
                eq("job-1"), any(CorrelationData.class));
        verify(jdbc).update(contains("SET status='pending'"), eq("e1"));
        verify(jdbc, never()).update(contains("status='sent'"), any(Object[].class));
    }

    @Test
    void staleSendingRowsAreResetToPending() {
        publisher.recoverStaleSending();

        verify(jdbc).update(contains("status='sending'"));
    }
}
