package com.gameweare.api.voucher;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
class VoucherQueueConfig {
    static final String EXCHANGE = "gameweare.voucher";
    static final String QUEUE = "gameweare.voucher.claims";
    static final String RETRY_EXCHANGE = "gameweare.voucher.retry";
    static final String RETRY_SHORT = "gameweare.voucher.retry.5s";
    static final String RETRY_LONG = "gameweare.voucher.retry.30s";
    static final String DEAD = "gameweare.voucher.dead";

    @Bean DirectExchange voucherExchange() { return new DirectExchange(EXCHANGE, true, false); }
    @Bean DirectExchange voucherRetryExchange() { return new DirectExchange(RETRY_EXCHANGE, true, false); }
    @Bean Queue voucherQueue() { return QueueBuilder.durable(QUEUE).build(); }
    @Bean Queue voucherRetryShort() {
        return QueueBuilder.durable(RETRY_SHORT).ttl(5_000)
                .deadLetterExchange(EXCHANGE).deadLetterRoutingKey("claim").build();
    }
    @Bean Queue voucherRetryLong() {
        return QueueBuilder.durable(RETRY_LONG).ttl(30_000)
                .deadLetterExchange(EXCHANGE).deadLetterRoutingKey("claim").build();
    }
    @Bean Queue voucherDead() { return QueueBuilder.durable(DEAD).build(); }
    @Bean Binding voucherBinding(Queue voucherQueue, DirectExchange voucherExchange) {
        return BindingBuilder.bind(voucherQueue).to(voucherExchange).with("claim");
    }
    @Bean Binding voucherShortBinding(Queue voucherRetryShort, DirectExchange voucherRetryExchange) {
        return BindingBuilder.bind(voucherRetryShort).to(voucherRetryExchange).with("short");
    }
    @Bean Binding voucherLongBinding(Queue voucherRetryLong, DirectExchange voucherRetryExchange) {
        return BindingBuilder.bind(voucherRetryLong).to(voucherRetryExchange).with("long");
    }
}
