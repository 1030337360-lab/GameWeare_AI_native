package com.gameweare.api.create;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.event.ModelCallEndEvent;
import io.agentscope.core.middleware.MiddlewareBase;
import io.agentscope.core.middleware.ModelCallInput;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;
import org.springframework.jdbc.core.JdbcTemplate;
import reactor.core.publisher.Flux;

/** Audits every game and cover model call against the same create job. */
final class AgentModelUsageMeter implements MiddlewareBase {
    private final JdbcTemplate db;
    private final String jobId;
    private final String model;
    private long input;
    private long output;
    private long calls;
    private long unknownCalls;

    AgentModelUsageMeter(JdbcTemplate db, String jobId, String model) {
        this.db = db;
        this.jobId = jobId;
        this.model = model;
    }

    @Override
    public Flux<AgentEvent> onModelCall(Agent agent, RuntimeContext ctx,
            ModelCallInput input, Function<ModelCallInput, Flux<AgentEvent>> next) {
        return Flux.defer(() -> {
            synchronized (this) {
                if (unknownCalls > 0)
                    throw new IllegalStateException("AI provider usage is unresolved");
            }
            String callId = UUID.randomUUID().toString();
            AtomicBoolean ended = new AtomicBoolean();
            db.update("INSERT INTO agent_model_calls(id,job_id,model,state) VALUES(?,?,?,'pending')",
                    callId, jobId, model);
            return next.apply(input).doOnNext(event -> {
                if (event instanceof ModelCallEndEvent end && ended.compareAndSet(false, true)) {
                    var usage = end.getUsage();
                    db.update("UPDATE agent_model_calls SET state=?,provider_reply_id=?,prompt_tokens=?,"
                                    + "completion_tokens=?,ended_at=NOW(6) WHERE id=?",
                            usage == null ? "unknown" : "completed",
                            end.getReplyId() == null ? null : end.getReplyId().substring(0,
                                    Math.min(255, end.getReplyId().length())),
                            usage == null ? null : usage.getInputTokens(),
                            usage == null ? null : usage.getOutputTokens(), callId);
                    synchronized (this) {
                        if (usage == null) { unknownCalls++; return; }
                        this.input = Math.addExact(this.input, usage.getInputTokens());
                        this.output = Math.addExact(this.output, usage.getOutputTokens());
                        this.calls++;
                    }
                }
            }).doOnError(error -> markUnknown(callId, ended))
                    .doOnCancel(() -> markUnknown(callId, ended));
        });
    }

    private void markUnknown(String callId, AtomicBoolean ended) {
        if (ended.compareAndSet(false, true)) {
            db.update("UPDATE agent_model_calls SET state='unknown',"
                    + "ended_at=NOW(6) WHERE id=? AND state='pending'", callId);
            synchronized (this) { unknownCalls++; }
        }
    }

    synchronized long input() { return input; }
    synchronized long output() { return output; }
    synchronized long calls() { return calls; }
    synchronized long unknownCalls() { return unknownCalls; }
    synchronized long total() { return Math.addExact(input, output); }
}
