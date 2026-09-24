package com.gameweare.api.config;

import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

@Component
public class OutboxPublisher {
    private final JdbcTemplate jdbc;
    private final RabbitTemplate rabbit;

    public OutboxPublisher(JdbcTemplate jdbc, RabbitTemplate rabbit) {
        this.jdbc = jdbc;
        this.rabbit = rabbit;
    }

    @Scheduled(fixedDelayString = "${gameweare.outbox.interval-ms:1000}")
    public void publishPending() {
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT id, aggregate_id FROM outbox_events
                WHERE status='pending' AND available_at <= CURRENT_TIMESTAMP(6)
                ORDER BY created_at LIMIT 100
                """);
        for (Map<String, Object> row : rows) {
            String id = row.get("id").toString();
            int claimed = jdbc.update("UPDATE outbox_events SET status='sending', sending_at=CURRENT_TIMESTAMP(6), attempts=attempts+1 WHERE id=? AND status='pending'", id);
            if (claimed == 0) continue;
            try {
                CorrelationData confirmation = new CorrelationData(id);
                rabbit.convertAndSend(InfrastructureConfig.CREATE_EXCHANGE, "job.created",
                        row.get("aggregate_id").toString(), confirmation);
                var result = confirmation.getFuture().get(5, TimeUnit.SECONDS);
                if (!result.isAck() || confirmation.getReturned() != null) {
                    throw new IllegalStateException("RabbitMQ did not route the job event");
                }
                jdbc.update("UPDATE outbox_events SET status='sent', sent_at=CURRENT_TIMESTAMP(6) WHERE id=?", id);
            } catch (Exception ex) {
                jdbc.update("UPDATE outbox_events SET status='pending', sending_at=NULL, available_at=DATE_ADD(CURRENT_TIMESTAMP(6), INTERVAL LEAST(POW(2, LEAST(attempts, 8)), 300) SECOND) WHERE id=?", id);
            }
        }
    }

    @Scheduled(fixedDelay = 60000)
    public void recoverStaleSending() {
        jdbc.update("UPDATE outbox_events SET status='pending', sending_at=NULL WHERE status='sending' AND sending_at < DATE_SUB(CURRENT_TIMESTAMP(6), INTERVAL 5 MINUTE)");
    }
}
