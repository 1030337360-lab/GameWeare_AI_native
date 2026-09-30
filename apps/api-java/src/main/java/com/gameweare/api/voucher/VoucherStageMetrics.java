package com.gameweare.api.voucher;

import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;
import org.springframework.stereotype.Component;

/** Low-cardinality, aggregable timings for the voucher claim path. */
@Component
public class VoucherStageMetrics {
    private static final Duration[] BUCKETS = {
            Duration.ofNanos(100_000), Duration.ofNanos(250_000), Duration.ofNanos(500_000),
            Duration.ofMillis(1), Duration.ofMillis(2), Duration.ofMillis(3), Duration.ofMillis(5),
            Duration.ofMillis(7), Duration.ofMillis(10), Duration.ofMillis(15), Duration.ofMillis(20),
            Duration.ofMillis(30), Duration.ofMillis(50), Duration.ofMillis(75), Duration.ofMillis(100),
            Duration.ofMillis(150), Duration.ofMillis(200), Duration.ofMillis(300),
            Duration.ofMillis(500), Duration.ofMillis(750), Duration.ofSeconds(1),
            Duration.ofSeconds(2), Duration.ofSeconds(3), Duration.ofSeconds(5),
            Duration.ofSeconds(10), Duration.ofSeconds(20), Duration.ofSeconds(30),
            Duration.ofSeconds(60), Duration.ofSeconds(120), Duration.ofSeconds(180),
            Duration.ofSeconds(300), Duration.ofSeconds(600)
    };

    private final MeterRegistry registry;
    private final ConcurrentHashMap<String, Timer> timers = new ConcurrentHashMap<>();

    public VoucherStageMetrics(MeterRegistry registry) { this.registry = registry; }

    public <T> T time(String stage, Supplier<T> action) {
        long started = System.nanoTime();
        try { return action.get(); }
        finally { record(stage, System.nanoTime() - started); }
    }

    public void time(String stage, Runnable action) {
        long started = System.nanoTime();
        try { action.run(); }
        finally { record(stage, System.nanoTime() - started); }
    }

    public void record(String stage, long nanos) {
        if (nanos < 0) return;
        timers.computeIfAbsent(stage, name -> Timer.builder("gameweare.voucher.stage")
                .description("Voucher claim stage duration")
                .tag("stage", name)
                .publishPercentileHistogram()
                .serviceLevelObjectives(BUCKETS)
                .minimumExpectedValue(Duration.ofNanos(100_000))
                .maximumExpectedValue(Duration.ofMinutes(10))
                .register(registry)).record(nanos, TimeUnit.NANOSECONDS);
    }
}
