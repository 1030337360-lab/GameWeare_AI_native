package com.gameweare.api.config;

import com.gameweare.api.config.dao.OutboxMapper;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Component
public class OutboxPublisher {
    private final OutboxMapper outbox;
    private final RabbitTemplate rabbit;

    public OutboxPublisher(OutboxMapper outbox, RabbitTemplate rabbit) {
        this.outbox = outbox;
        this.rabbit = rabbit;
    }

    @Scheduled(fixedDelayString = "${gameweare.outbox.interval-ms:1000}")
    public void publishPending() {
        List<Map<String, Object>> rows = outbox.pending();
        for (Map<String, Object> row : rows) {
            String id = row.get("id").toString();
            int claimed = outbox.claim(id);
            if (claimed == 0) continue;
            try {
                CorrelationData confirmation = new CorrelationData(id);
                rabbit.convertAndSend(InfrastructureConfig.CREATE_EXCHANGE, "job.created",
                        row.get("aggregate_id").toString(), confirmation);
                var result = confirmation.getFuture().get(5, TimeUnit.SECONDS);
                if (!result.isAck() || confirmation.getReturned() != null) {
                    throw new IllegalStateException("RabbitMQ did not route the job event");
                }
                outbox.markSent(id);
            } catch (Exception ex) {
                outbox.retryLater(id);
            }
        }
    }

    @Scheduled(fixedDelay = 60000)
    public void recoverStaleSending() {
        outbox.recoverStale();
    }
}
