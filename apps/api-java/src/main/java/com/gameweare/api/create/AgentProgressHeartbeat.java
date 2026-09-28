package com.gameweare.api.create;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

/** Tracks model traffic as a progress signal; the Worker also checks its thread and distributed lock. */
@Component
final class AgentProgressHeartbeat {
    private final ConcurrentHashMap<String, AtomicLong> last = new ConcurrentHashMap<>();

    void start(String jobId) { last.put(jobId, new AtomicLong(System.nanoTime())); }
    void touch(String jobId) {
        if (jobId != null) {
            AtomicLong value = last.get(jobId);
            if (value != null) value.set(System.nanoTime());
        }
    }
    long last(String jobId) {
        AtomicLong value = last.get(jobId);
        return value == null ? 0 : value.get();
    }
    void stop(String jobId) { last.remove(jobId); }
}
