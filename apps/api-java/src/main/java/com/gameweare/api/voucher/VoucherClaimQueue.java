package com.gameweare.api.voucher;

import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
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

    public VoucherClaimQueue(StringRedisTemplate redis, RabbitTemplate rabbit, VoucherCampaignService campaigns) {
        this.redis = redis; this.rabbit = rabbit; this.campaigns = campaigns;
    }

    /** Redis Stream is the durable handoff created in the same Lua invocation as the pre-debit. */
    @Scheduled(fixedDelayString = "${gameweare.voucher.relay-ms:500}")
    public void relay() {
        try {
            List<MapRecord<String, Object, Object>> records = redis.opsForStream().read(
                    StreamReadOptions.empty().count(100),
                    StreamOffset.create(VoucherCampaignService.STREAM, ReadOffset.from("0-0")));
            if (records == null) return;
            for (MapRecord<String, Object, Object> record : records) {
                Map<Object, Object> value = record.getValue();
                String payload = value.get("campaign") + "|" + value.get("user") + "|"
                        + value.get("id") + "|" + value.get("remaining") + "|0";
                publish(VoucherQueueConfig.EXCHANGE, "claim", payload);
                redis.opsForStream().delete(VoucherCampaignService.STREAM, record.getId());
            }
        } catch (Exception unavailable) {
            LOG.warn("Voucher claim relay will retry: {}", unavailable.toString());
        }
    }

    @RabbitListener(queues = VoucherQueueConfig.QUEUE)
    public void consume(String payload) {
        String[] fields = payload.split("\\|", -1);
        if (fields.length != 5) throw new IllegalArgumentException("Malformed voucher claim event");
        String campaignId = fields[0], userId = fields[1], reservationId = fields[2];
        int remaining = Integer.parseInt(fields[3]);
        int attempt = Integer.parseInt(fields[4]);
        try {
            campaigns.issue(campaignId, userId, reservationId, remaining);
        } catch (Exception failure) {
            LOG.warn("Voucher claim {} attempt {} failed: {}", reservationId, attempt, failure.toString());
            if (attempt < 3) {
                String route = attempt == 0 ? "short" : "long";
                publish(VoucherQueueConfig.RETRY_EXCHANGE, route,
                        campaignId + "|" + userId + "|" + reservationId + "|" + remaining + "|" + (attempt + 1));
                return;
            }
            // The claim is provisional until MySQL commits. Compare reservation identity before release.
            campaigns.compensate(campaignId, userId, reservationId);
            publish("", VoucherQueueConfig.DEAD, payload);
        }
    }

    private void publish(String exchange, String route, String body) {
        try {
            CorrelationData confirmation = new CorrelationData(java.util.UUID.randomUUID().toString());
            rabbit.convertAndSend(exchange, route, body, confirmation);
            var result = confirmation.getFuture().get(5, TimeUnit.SECONDS);
            if (!result.isAck() || confirmation.getReturned() != null)
                throw new IllegalStateException("RabbitMQ did not route voucher event");
        } catch (Exception failure) { throw new IllegalStateException("Voucher event publish failed", failure); }
    }
}
