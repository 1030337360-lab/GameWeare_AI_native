package com.gameweare.api.create;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import okhttp3.Call;
import org.springframework.stereotype.Component;

/** Interrupts a worker on this instance; the database status remains authoritative across instances. */
@Component
final class CreateCancellationRegistry {
    private static final ThreadLocal<Worker> CURRENT = new ThreadLocal<>();
    private final Map<String, Worker> workers = new ConcurrentHashMap<>();

    void register(String jobId) {
        Worker worker = new Worker(Thread.currentThread(), new AtomicBoolean(), new AtomicReference<>());
        workers.put(jobId, worker);
        CURRENT.set(worker);
    }

    boolean unregister(String jobId) {
        Worker worker = CURRENT.get();
        if (worker != null) workers.remove(jobId, worker);
        CURRENT.remove();
        return worker != null && worker.canceled().get();
    }

    static void track(Call call) {
        Worker worker = CURRENT.get();
        if (worker == null) return;
        worker.call().set(call);
        if (worker.canceled().get()) call.cancel();
    }

    static void untrack(Call call) {
        Worker worker = CURRENT.get();
        if (worker != null) worker.call().compareAndSet(call, null);
    }

    void cancel(String jobId) {
        Worker worker = workers.get(jobId);
        if (worker != null) {
            worker.canceled().set(true);
            Call call = worker.call().get();
            if (call != null) call.cancel();
            worker.thread().interrupt();
        }
    }

    private record Worker(Thread thread, AtomicBoolean canceled, AtomicReference<Call> call) {}
}
