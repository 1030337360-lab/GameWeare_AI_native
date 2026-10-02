package com.gameweare.api.config;

import com.gameweare.api.config.dao.OutboxMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Outbox delivery: atomic claim, retry with backoff, stale-send recovery. */
class OutboxPublisherTest {
    private final OutboxMapper outbox = mock(OutboxMapper.class);
    private final RabbitTemplate rabbit = mock(RabbitTemplate.class);
    private final OutboxPublisher publisher = new OutboxPublisher(outbox, rabbit);

    private void pendingEvent() {
        when(outbox.pending())
                .thenReturn(List.of(Map.<String, Object>of("id", "e1", "aggregate_id", "job-1")));
    }

    @Test
    void eventClaimedByAnotherPublisherIsSkipped() {
        pendingEvent();
        when(outbox.claim("e1")).thenReturn(0);

        publisher.publishPending();

        verify(rabbit, never()).convertAndSend(anyString(), anyString(), any(Object.class), any(CorrelationData.class));
        verify(outbox, never()).markSent("e1");
    }

    @Test
    void brokerFailureRequeuesEventWithBackoff() {
        pendingEvent();
        when(outbox.claim("e1")).thenReturn(1);
        doThrow(new RuntimeException("broker unreachable"))
                .when(rabbit).convertAndSend(anyString(), anyString(), any(Object.class), any(CorrelationData.class));

        publisher.publishPending();

        verify(rabbit).convertAndSend(eq(InfrastructureConfig.CREATE_EXCHANGE), eq("job.created"),
                eq("job-1"), any(CorrelationData.class));
        verify(outbox).retryLater("e1");
        verify(outbox, never()).markSent("e1");
    }

    @Test
    void staleSendingRowsAreResetToPending() {
        publisher.recoverStaleSending();

        verify(outbox).recoverStale();
    }
}
