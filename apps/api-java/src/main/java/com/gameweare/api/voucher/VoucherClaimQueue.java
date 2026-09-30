package com.gameweare.api.voucher;

import com.rabbitmq.client.Channel;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.support.AmqpHeaders;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.messaging.handler.annotation.Header;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class VoucherClaimQueue {
    private static final Logger LOG = LoggerFactory.getLogger(VoucherClaimQueue.class);
    private final StringRedisTemplate redis;
    private final RabbitTemplate rabbit;
    private final VoucherCampaignService campaigns;
    private final VoucherStageMetrics metrics;

    public VoucherClaimQueue(StringRedisTemplate redis, RabbitTemplate rabbit,
                             VoucherCampaignService campaigns, VoucherStageMetrics metrics) {
        this.redis = redis; this.rabbit = rabbit; this.campaigns = campaigns; this.metrics = metrics;
    }

    /** Redis Stream is the durable handoff created in the same Lua invocation as the pre-debit. */
    @Scheduled(fixedDelayString = "${gameweare.voucher.relay-ms:500}")
    public void relay() {
        try {
            List<MapRecord<String, Object, Object>> records = metrics.time("relay.redis_stream_read", () -> redis.opsForStream().read(
                    StreamReadOptions.empty().count(100),
                    StreamOffset.create(VoucherCampaignService.STREAM, ReadOffset.from("0-0"))));
            if (records == null) return;
            for (MapRecord<String, Object, Object> record : records) {
                Map<Object, Object> value = record.getValue();
                String payload = value.get("campaign") + "|" + value.get("user") + "|"
                        + value.get("id") + "|" + value.get("remaining") + "|0|"
                        + (value.get("created") == null ? "" : value.get("created"));
                publish("relay.rabbit_publish_confirm", VoucherQueueConfig.EXCHANGE, "claim", payload);
                metrics.time("relay.redis_stream_delete",
                        () -> redis.opsForStream().delete(VoucherCampaignService.STREAM, record.getId()));
            }
        } catch (Exception unavailable) {
            LOG.warn("Voucher claim relay will retry: {}", unavailable.toString());
        }
    }

    @RabbitListener(queues = VoucherQueueConfig.QUEUE, ackMode = "MANUAL")
    public void consume(String payload, Channel channel,
                        @Header(AmqpHeaders.DELIVERY_TAG) long deliveryTag) throws IOException {
        try {
            process(payload);
        } catch (RuntimeException failure) {
            LOG.warn("Voucher delivery will be redelivered: {}", failure.toString());
            long started = System.nanoTime();
            channel.basicNack(deliveryTag, false, true);
            metrics.record("consumer.manual_nack", System.nanoTime() - started);
            return;
        }
        long started = System.nanoTime();
        channel.basicAck(deliveryTag, false);
        metrics.record("consumer.manual_ack", System.nanoTime() - started);
    }

    private void process(String payload) {
        String[] fields = payload.split("\\|", -1);
        if (fields.length != 5 && fields.length != 6) {
            publish("consumer.dead_publish_confirm", "", VoucherQueueConfig.DEAD, payload);
            return;
        }
        String campaignId = fields[0], userId = fields[1], reservationId = fields[2];
        int remaining;
        int attempt;
        long createdAt;
        try {
            remaining = Integer.parseInt(fields[3]);
            attempt = Integer.parseInt(fields[4]);
            createdAt = fields.length == 6 && !fields[5].isBlank() ? Long.parseLong(fields[5]) : -1;
        } catch (NumberFormatException malformed) {
            publish("consumer.dead_publish_confirm", "", VoucherQueueConfig.DEAD, payload);
            return;
        }
        try {
            boolean issued = metrics.time("consumer.issue_transaction",
                    () -> campaigns.issue(campaignId, userId, reservationId, remaining));
            if (issued && createdAt > 0) {
                metrics.record("consumer.reservation_to_issue",
                        TimeUnit.MILLISECONDS.toNanos(Math.max(0, System.currentTimeMillis() - createdAt)));
            }
        } catch (Exception failure) {
            LOG.warn("Voucher claim {} attempt {} failed: {}", reservationId, attempt, failure.toString());
            if (attempt < 3) {
                String route = attempt == 0 ? "short" : "long";
                publish("consumer.retry_publish_confirm", VoucherQueueConfig.RETRY_EXCHANGE, route,
                        campaignId + "|" + userId + "|" + reservationId + "|" + remaining + "|"
                                + (attempt + 1) + "|" + (createdAt < 0 ? "" : createdAt));
                return;
            }
            // The claim is provisional until MySQL commits. Compare reservation identity before release.
            campaigns.compensate(campaignId, userId, reservationId);
            publish("consumer.dead_publish_confirm", "", VoucherQueueConfig.DEAD, payload);
        }
    }

    private void publish(String stage, String exchange, String route, String body) {
        metrics.time(stage, () -> {
            try {
                CorrelationData confirmation = new CorrelationData(java.util.UUID.randomUUID().toString());
                rabbit.convertAndSend(exchange, route, body, message -> {
                    message.getMessageProperties().setDeliveryMode(MessageDeliveryMode.PERSISTENT);
                    return message;
                }, confirmation);
                var result = confirmation.getFuture().get(5, TimeUnit.SECONDS);
                if (!result.isAck() || confirmation.getReturned() != null)
                    throw new IllegalStateException("RabbitMQ did not route voucher event");
            } catch (Exception failure) {
                throw new IllegalStateException("Voucher event publish failed", failure);
            }
        });
    }
}
