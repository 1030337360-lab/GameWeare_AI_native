package com.gameweare.api.create;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.gameweare.api.billing.TokenBillingService;
import com.gameweare.api.config.InfrastructureConfig;
import com.gameweare.api.voucher.GenerationVoucherService;
import io.minio.MinioClient;
import io.minio.GetObjectArgs;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;
import java.util.List;
import java.util.ArrayList;
import java.util.Base64;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.TimeUnit;

@Component
public class CreateWorker {
    private static final Logger LOG = LoggerFactory.getLogger(CreateWorker.class);
    private static final ObjectMapper JSON = new ObjectMapper();
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final CreateService service;
    private final TokenBillingService billing;
    private final GenerationVoucherService vouchers;
    private final MinioClient minio;
    private final AgentScopeCreateEngine agentScope;
    private final ArtifactValidator artifactValidator;
    private final CoverReActEngine coverReAct;
    private final String bucket;
    private final Map<String, ActiveRun> activeLeases = new ConcurrentHashMap<>();
    @org.springframework.beans.factory.annotation.Autowired
    private RedissonClient redisson;
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private AgentProgressHeartbeat heartbeat;
    @Value("${gameweare.agent.stall-timeout-minutes:25}")
    private long stallTimeoutMinutes = 25;
    @org.springframework.beans.factory.annotation.Autowired(required = false)
    private CreateCancellationRegistry cancellations;

    public CreateWorker(JdbcTemplate db, TransactionTemplate tx, CreateService service, TokenBillingService billing,
                        GenerationVoucherService vouchers,
                        MinioClient minio, AgentScopeCreateEngine agentScope, ArtifactValidator artifactValidator,
                        CoverReActEngine coverReAct,
                        @Value("${gameweare.minio.bucket}") String bucket) {
        this.db = db; this.tx = tx; this.service = service; this.billing = billing; this.vouchers = vouchers; this.minio = minio;
        this.agentScope = agentScope; this.artifactValidator = artifactValidator;
        this.coverReAct = coverReAct; this.bucket = bucket;
    }

    // Each consumer owns one long-running job. Keep prefetch at one so idle consumers
    // can receive the next job instead of leaving it reserved behind an active run.
    @RabbitListener(queues = InfrastructureConfig.CREATE_QUEUE,
            concurrency = "${gameweare.agent.worker-concurrency:2}")
    public void consume(String jobId) {
        RLock lock = redisson.getLock("create:job:run:" + jobId);
        try {
            // No explicit leaseTime: Redisson's watchdog renews while this JVM owns the lock.
            if (!lock.tryLock(0, TimeUnit.SECONDS)) return;
            try {
                consumeLocked(jobId, lock);
            } finally {
                if (lock.isHeldByCurrentThread()) lock.unlock();
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Interrupted acquiring create job lock", interrupted);
        }
    }

    private void consumeLocked(String jobId, RLock lock) {
        String leaseToken = UUID.randomUUID().toString();
        Map<String, Object> job = tx.execute(s -> {
            int changed = db.update("UPDATE create_jobs SET status='generating',lease_token=?,lease_expires_at=DATE_ADD(NOW(), INTERVAL 10 MINUTE),attempts=attempts+1,updated_at=NOW() WHERE id=? AND status='pending' AND attempts<3",
                    leaseToken, jobId);
            if (changed != 1) return null;
            step(jobId, 1, "generation", "running", "Generating game with configured AI provider");
            return db.queryForMap("SELECT * FROM create_jobs WHERE id=?", jobId);
        });
        if (job == null) return;
        ActiveRun active = new ActiveRun(leaseToken, Thread.currentThread(), lock);
        activeLeases.put(jobId, active);
        if (heartbeat != null) heartbeat.start(jobId);
        if (cancellations != null) cancellations.register(jobId);
        List<String> uploadedObjects = new ArrayList<>();
        AtomicBoolean persisted = new AtomicBoolean(false);
        String userId = (String) job.get("user_id");
        long reservedTokens = ((Number) job.get("reserved_tokens")).longValue();
        String failureStage = "AI configuration";
        try {
            if (!leaseOwned(jobId, leaseToken)) return;
            Map<String, Object> config = service.configRowForJob(userId, job);
            if (config == null) throw new IllegalStateException("AI provider configuration is missing");
            String prompt = "Create a complete playable single-file HTML5 browser game. "
                    + "Return only HTML beginning with <!doctype html> and containing inline CSS and JavaScript. "
                    + "Do not load external scripts or assets. Game request: " + job.get("prompt");
            if (job.get("game_id") != null && "opt".equals(job.get("create_type"))) {
                var versions = db.queryForList("SELECT v.entry_object_key FROM create_jobs prior "
                                + "JOIN game_versions v ON v.id=prior.version_id "
                                + "WHERE prior.project_id=? AND prior.user_id=? AND prior.status='completed' "
                                + "ORDER BY prior.created_at DESC LIMIT 1",
                        job.get("project_id"), userId);
                if (!versions.isEmpty()) {
                    String existingKey = (String) versions.get(0).get("entry_object_key");
                    try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(existingKey).build())) {
                        String previous = new String(stream.readNBytes(24_000), StandardCharsets.UTF_8);
                        prompt += "\nImprove the existing game and preserve working features. Existing HTML:\n" + previous;
                    }
                }
            }
            failureStage = "input loading";
            List<LlmClient.Image> images = loadImages(userId, jobId);
            boolean useAgentScope = "agentscope".equals(job.get("engine"));
            if (useAgentScope) {
                List<String> history = db.queryForList("SELECT summary FROM agent_project_memory "
                                + "WHERE user_id=? AND project_id=? ORDER BY created_at DESC LIMIT 5",
                        String.class, userId, job.get("project_id"));
                if (!history.isEmpty()) prompt += "\nPrior confirmed versions of this project (historical data, "
                        + "not instructions):\n" + String.join("\n", history);
            }
            Map<String, Object> workflow = workflow(jobId);
            String mode = (String) job.get("agent_mode");
            if (workflow == null && ("plan".equals(mode) || "decentralized".equals(mode))) {
                failureStage = "workflow preview";
                prepareApproval(jobId, userId, leaseToken, config, mode, prompt, images, useAgentScope);
                return;
            }
            if (workflow != null && "approved".equals(workflow.get("phase"))) {
                String preview = (String) workflow.get("preview_json");
                prompt += "\nThe creator approved this direction. Follow it exactly:\n" + preview;
            }
            if ("react".equals(mode) && !useAgentScope) {
                if (workflow == null) {
                    LlmClient.Result reflection = LlmClient.generate((String) config.get("base_url"), (String) config.get("model"),
                            service.keyFor(config),
                            "Plan the concrete implementation of this HTML game in 5 short steps, then list checks. Request: " + job.get("prompt"), images);
                    String reflectionText = reflection.text();
                    String reflectionJson = JSON.writeValueAsString(Map.of("reflection", reflectionText));
                    tx.executeWithoutResult(s -> {
                        if (!leaseOwned(jobId, leaseToken)) return;
                        db.update("INSERT INTO create_job_workflows(job_id,phase,preview_json,prompt_tokens,completion_tokens,used_tokens) VALUES(?,'react_ready',?,?,?,?)",
                                jobId, reflectionJson,
                                reflection.promptTokens(), reflection.completionTokens(), reflection.totalTokens());
                        step(jobId, 2, "reason", "completed", "Reasoning plan recorded");
                    });
                    workflow = workflow(jobId);
                }
                if (workflow != null) prompt += "\nUse this reasoning plan and verify its checks:\n" + workflow.get("preview_json");
            }
            long previousTokens = workflow == null ? 0 : ((Number) workflow.get("used_tokens")).longValue();
            long previousPrompt = workflow == null ? 0 : ((Number) workflow.get("prompt_tokens")).longValue();
            long previousCompletion = workflow == null ? 0 : ((Number) workflow.get("completion_tokens")).longValue();
            failureStage = "AI generation";
            LlmClient.Result generated = useAgentScope
                    ? agentScope.run(jobId, userId, mode, prompt, config,
                            service.keyFor(config), images, false)
                    : LlmClient.generateValidatedGame((String) config.get("base_url"),
                            (String) config.get("model"), service.keyFor(config), prompt, images,
                            new GameValidationTool(jobId, artifactValidator), result ->
                                    step(jobId, nextStepNo(jobId), "game_validation_tool",
                                            result.passed() ? "completed" : "failed", result.feedback()));
            if (!leaseOwned(jobId, leaseToken)) return;
            failureStage = "HTML/JavaScript validation";
            String html = generated.text();
            ArtifactValidator.Result validation = artifactValidator.validate(html);
            if (!validation.ok())
                throw new IllegalStateException("Generated game did not pass HTML/JavaScript validation: "
                        + ValidationDiagnostics.format(validation.diagnostics()));
            html = validation.normalizedHtml();
            long gameTokens = Math.addExact(previousTokens, generated.totalTokens());
            String title = CreateService.title((String) job.get("prompt"));
            boolean newGame = job.get("game_id") == null;
            CoverGenerator.Cover cover;
            if (newGame) {
                step(jobId, nextStepNo(jobId), "cover_generation_started", "running",
                        "Starting an independent cover ReAct agent with the complete validated game source");
                failureStage = "cover generation";
                cover = coverReAct.generate(jobId, userId, config,
                        service.keyFor(config),
                        title, (String) job.get("prompt"), html);
            } else {
                cover = null;
                step(jobId, nextStepNo(jobId), "cover_reused", "completed", "Keeping the original game cover");
            }
            if (!leaseOwned(jobId, leaseToken)) return;
            long coverPromptTokens = cover == null ? 0 : cover.promptTokens();
            long coverCompletionTokens = cover == null ? 0 : cover.completionTokens();
            long totalTokens = Math.addExact(gameTokens, Math.addExact(coverPromptTokens, coverCompletionTokens));
            String gameId = job.get("game_id") == null ? UUID.randomUUID().toString() : (String) job.get("game_id");
            String versionId = UUID.randomUUID().toString();
            String key = "games/" + gameId + "/" + versionId + "/index.html";
            String coverKey = cover == null ? null : "games/" + gameId + "/" + versionId + "/cover.svg";
            byte[] bytes = html.getBytes(StandardCharsets.UTF_8);
            failureStage = "artifact upload";
            uploadedObjects.add(key);
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(key)
                    .stream(new ByteArrayInputStream(bytes), bytes.length, -1).contentType("text/html; charset=utf-8").build());
            if (cover != null) {
                uploadedObjects.add(coverKey);
                minio.putObject(PutObjectArgs.builder().bucket(bucket).object(coverKey)
                        .stream(new ByteArrayInputStream(cover.bytes()), cover.bytes().length, -1)
                        .contentType("image/svg+xml").build());
                step(jobId, nextStepNo(jobId), "cover_uploaded", "completed",
                        cover.degraded() ? "Local fallback cover stored; " + cover.failureReason()
                                : "AI-generated cover stored");
            }
            failureStage = "database persistence";
            tx.executeWithoutResult(s -> {
                List<Map<String, Object>> current = db.queryForList("SELECT id FROM create_jobs WHERE id=? AND status='generating' AND lease_token=? AND lease_expires_at>NOW() FOR UPDATE", jobId, leaseToken);
                if (current.isEmpty()) return;
                if (job.get("game_id") == null) {
                    db.update("INSERT INTO games(id,slug,title,description,author_id,publish_status,visibility,created_at,updated_at) VALUES(?,?,?,?,?,'draft','private',NOW(),NOW())",
                            gameId, "game-" + gameId, title, title, userId);
                } else {
                    db.queryForObject("SELECT id FROM games WHERE id=? AND author_id=? FOR UPDATE", String.class, gameId, userId);
                }
                int version = db.queryForObject("SELECT COALESCE(MAX(version_no),0)+1 FROM game_versions WHERE game_id=?", Integer.class, gameId);
                db.update("INSERT INTO game_versions(id,game_id,version_no,entry_object_key,runtime,build_status,safety_status,entry_file,storage_prefix,source_job_id) VALUES(?,?,?,?,'iframe-html5','passed','passed','index.html',?,?)",
                        versionId, gameId, version, key, "games/" + gameId + "/" + versionId, jobId);
                db.update("INSERT INTO assets(id,owner_id,game_id,version_id,job_id,kind,bucket,object_key,content_type,size_bytes) VALUES(?,?,?,?,?,'html',?,?,?,?)",
                        UUID.randomUUID().toString(), userId, gameId, versionId, jobId, bucket, key, "text/html; charset=utf-8", bytes.length);
                if (cover != null)
                    db.update("INSERT INTO assets(id,owner_id,game_id,version_id,job_id,kind,bucket,object_key,content_type,size_bytes) VALUES(?,?,?,?,?,'cover',?,?,?,?)",
                            UUID.randomUUID().toString(), userId, gameId, versionId, jobId, bucket, coverKey,
                            "image/svg+xml", cover.bytes().length);
                if (newGame)
                    db.update("UPDATE games SET current_version_id=?,cover_object_key=?,updated_at=NOW() WHERE id=?",
                            versionId, coverKey, gameId);
                db.update("UPDATE create_projects SET game_id=?,status='completed',updated_at=NOW() WHERE id=?", gameId, job.get("project_id"));
                db.update("UPDATE create_jobs SET game_id=?,version_id=?,actual_tokens=?,status='completed',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=?",
                        gameId, versionId, totalTokens, jobId);
                db.update("INSERT INTO model_usage_events(id,job_id,provider,model,prompt_tokens,completion_tokens,total_tokens) VALUES(?,?,?,?,?,?,?)",
                        UUID.randomUUID().toString(), jobId, config.get("provider"), config.get("model"),
                        previousPrompt + generated.promptTokens() + coverPromptTokens,
                        previousCompletion + generated.completionTokens() + coverCompletionTokens, totalTokens);
                if (useAgentScope) {
                    String request = (String) job.get("prompt");
                    String summary = "Validated version " + version + ": "
                            + request.substring(0, Math.min(request.length(), 1000));
                    db.update("INSERT INTO agent_project_memory(id,user_id,project_id,source_job_id,game_version_id,summary) "
                                    + "VALUES(?,?,?,?,?,?)",
                            UUID.randomUUID().toString(), userId, job.get("project_id"), jobId, versionId, summary);
                }
                step(jobId, nextStepNo(jobId), "generation", "completed",
                        newGame ? "Game and cover generated and stored" : "Game optimized; original cover retained");
                if (reservedTokens > 0) billing.settle(userId, jobId, totalTokens);
                if ("voucher".equals(job.get("funding_mode"))) vouchers.consume(userId, jobId);
                org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                        new org.springframework.transaction.support.TransactionSynchronization() {
                            @Override public void afterCommit() { persisted.set(true); }
                        });
            });
        } catch (Exception ex) {
            LOG.error("Create job {} failed", jobId, ex);
            String error = CreateFailureDetails.describe(failureStage, ex);
            String failedStage = failureStage;
            tx.executeWithoutResult(s -> {
                int changed = db.update("UPDATE create_jobs SET status='failed',lease_token=NULL,lease_expires_at=NULL,error_message=?,updated_at=NOW() WHERE id=? AND status='generating' AND lease_token=?",
                        error, jobId, leaseToken);
                if (changed == 1) {
                    step(jobId, nextStepNo(jobId), failedStage, "failed", error);
                    billing.refund(userId, jobId);
                    vouchers.release(userId, jobId);
                }
            });
        } finally {
            activeLeases.remove(jobId, active);
            if (heartbeat != null) heartbeat.stop(jobId);
            if (cancellations != null && cancellations.unregister(jobId)) Thread.interrupted();
            if (!persisted.get()) for (String objectKey : uploadedObjects) {
                try { minio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(objectKey).build()); }
                catch (Exception cleanupError) { LOG.warn("Could not remove uncommitted object {}", objectKey, cleanupError); }
            }
        }
    }

    private Map<String, Object> workflow(String jobId) {
        var rows = db.queryForList("SELECT phase,preview_json,selected_candidate_id,prompt_tokens,completion_tokens,used_tokens FROM create_job_workflows WHERE job_id=?", jobId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private boolean leaseOwned(String jobId, String token) {
        Integer count = db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE id=? AND status='generating' AND lease_token=? AND lease_expires_at>NOW()", Integer.class, jobId, token);
        return count != null && count == 1;
    }

    private void prepareApproval(String jobId, String userId, String leaseToken, Map<String, Object> config,
                                 String mode, String prompt, List<LlmClient.Image> images,
                                 boolean useAgentScope) throws Exception {
        String instruction = "plan".equals(mode)
                ? "Return ONLY JSON object with plan (3-8 objects with id,title,goal,toolFamily,expectedOutput,acceptanceCheckRefs), risks (nonempty strings), acceptanceChecks (objects with id,description,type,severity). Plan this playable HTML5 game. Request: "
                : "Return ONLY JSON object with candidates: exactly 3 distinct objects, each with candidateId,title,conceptSummary,expertRole,expertDomain,expertIntro,styleTags (array),staticHtml (a self-contained simple HTML visual preview). Request: ";
        LlmClient.Result result = useAgentScope
                ? agentScope.run(jobId, userId, mode, prompt, config,
                        service.keyFor(config), images, true)
                : LlmClient.generate((String) config.get("base_url"), (String) config.get("model"),
                        service.keyFor(config), instruction + prompt, images);
        String raw = result.text().strip().replaceFirst("(?is)^```(?:json)?\\s*", "").replaceFirst("(?s)\\s*```$", "").strip();
        JsonNode parsed = JSON.readTree(raw);
        if (!parsed.isObject()) throw new IllegalStateException("AI provider returned invalid workflow preview");
        if ("plan".equals(mode)) {
            if (!parsed.path("plan").isArray() || parsed.path("plan").size() < 3 || parsed.path("plan").size() > 8
                    || !parsed.path("risks").isArray() || !parsed.path("acceptanceChecks").isArray())
                throw new IllegalStateException("AI provider returned an incomplete plan");
        } else {
            JsonNode candidates = parsed.path("candidates");
            if (!candidates.isArray() || candidates.size() != 3) throw new IllegalStateException("AI provider returned incomplete candidates");
            for (JsonNode candidate : candidates) {
                if (candidate.path("candidateId").asText().isBlank() || candidate.path("staticHtml").asText().isBlank())
                    throw new IllegalStateException("AI provider returned an incomplete candidate");
            }
        }
        String phase = "plan".equals(mode) ? "awaiting_plan" : "awaiting_selection";
        tx.executeWithoutResult(s -> {
            if (!leaseOwned(jobId, leaseToken)) return;
            db.update("INSERT INTO create_job_workflows(job_id,phase,preview_json,prompt_tokens,completion_tokens,used_tokens) VALUES(?,?,?,?,?,?)",
                    jobId, phase, raw, result.promptTokens(), result.completionTokens(), result.totalTokens());
            db.update("UPDATE create_jobs SET status=?,lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND lease_token=?",
                    "plan".equals(mode) ? "planning" : "reviewing", jobId, leaseToken);
            step(jobId, 2, phase, "completed", "Preview is ready for creator decision");
        });
    }

    private List<LlmClient.Image> loadImages(String userId, String jobId) throws Exception {
        List<LlmClient.Image> images = new ArrayList<>();
        for (Map<String, Object> asset : db.queryForList("SELECT a.bucket,a.object_key,a.content_type,a.size_bytes FROM create_job_inputs i JOIN assets a ON a.id=i.asset_id WHERE i.job_id=? AND a.owner_id=? AND a.kind='upload'",
                jobId, userId)) {
            long size = ((Number) asset.get("size_bytes")).longValue();
            if (size > 10 * 1024 * 1024) throw new IllegalStateException("Image exceeds provider input limit");
            try (var stream = minio.getObject(GetObjectArgs.builder().bucket((String) asset.get("bucket"))
                    .object((String) asset.get("object_key")).build())) {
                byte[] bytes = stream.readNBytes(10 * 1024 * 1024 + 1);
                if (bytes.length > 10 * 1024 * 1024) throw new IllegalStateException("Image exceeds provider input limit");
                images.add(new LlmClient.Image("data:" + asset.get("content_type") + ";base64," + Base64.getEncoder().encodeToString(bytes)));
            }
        }
        return images;
    }

    @Scheduled(fixedDelay = 30_000)
    public void renewActiveLeases() {
        activeLeases.forEach((jobId, active) -> {
            long lastProgress = Math.max(active.lastProgress.get(), heartbeat == null ? 0 : heartbeat.last(jobId));
            boolean healthy = active.owner.isAlive()
                    && TimeUnit.NANOSECONDS.toMinutes(System.nanoTime() - lastProgress) < stallTimeoutMinutes;
            try {
                if (healthy && active.lock != null)
                    healthy = active.lock.isHeldByThread(active.owner.getId());
            } catch (RuntimeException redisUnavailable) {
                healthy = false;
                LOG.warn("Cannot verify Redisson watchdog for create job {}", jobId, redisUnavailable);
            }
            if (!healthy) {
                LOG.warn("Agent worker for job {} lost its lock, thread, or progress heartbeat; expiring MySQL lease", jobId);
                db.update("UPDATE create_jobs SET lease_expires_at=NOW(),updated_at=NOW() WHERE id=? AND status='generating' AND lease_token=?",
                        jobId, active.token);
                if (cancellations != null) cancellations.cancel(jobId);
                try {
                    if (active.lock != null && active.lock.isHeldByThread(active.owner.getId()))
                        active.lock.unlockAsync(active.owner.getId()).toCompletableFuture().join();
                } catch (RuntimeException unlockFailure) {
                    LOG.warn("Could not release unhealthy create job lock {} yet", jobId, unlockFailure);
                }
                return;
            }
            int changed = db.update("UPDATE create_jobs SET lease_expires_at=DATE_ADD(NOW(), INTERVAL 10 MINUTE) WHERE id=? AND status='generating' AND lease_token=?",
                    jobId, active.token);
            if (changed == 0 && cancellations != null) cancellations.cancel(jobId);
        });
    }

    @Scheduled(fixedDelay = 60_000)
    public void recoverExpiredLeases() {
        for (Map<String, Object> row : db.queryForList("SELECT id,user_id,attempts FROM create_jobs WHERE status='generating' AND lease_expires_at<NOW() LIMIT 100")) {
            String id = (String) row.get("id");
            String userId = (String) row.get("user_id");
            tx.executeWithoutResult(s -> {
                int attempts = ((Number) row.get("attempts")).intValue();
                if (attempts >= 3) {
                    int changed = db.update("UPDATE create_jobs SET status='failed',error_message='Worker lease expired after retries',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='generating' AND lease_expires_at<NOW()", id);
                    if (changed == 1) { step(id, 4, "generation", "failed", "Worker lease expired after retries"); billing.refund(userId, id); vouchers.release(userId, id); }
                } else {
                    int changed = db.update("UPDATE create_jobs SET status='pending',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='generating' AND lease_expires_at<NOW()", id);
                    if (changed == 1) db.update("UPDATE outbox_events SET status='pending',available_at=NOW() WHERE aggregate_id=? AND event_type='job.created'", id);
                }
            });
        }
        // A Redis outage may reject a message before a worker can claim its MySQL lease.
        // Reopen its outbox event so a healthy instance can try again after recovery.
        for (String id : db.queryForList("SELECT id FROM create_jobs WHERE status='pending' AND attempts<3 AND updated_at<DATE_SUB(NOW(), INTERVAL 2 MINUTE) LIMIT 100", String.class)) {
            tx.executeWithoutResult(s -> {
                int changed = db.update("UPDATE create_jobs SET updated_at=NOW() WHERE id=? AND status='pending' AND updated_at<DATE_SUB(NOW(), INTERVAL 2 MINUTE)", id);
                if (changed == 1) db.update("UPDATE outbox_events SET status='pending',available_at=NOW() WHERE aggregate_id=? AND event_type='job.created' AND status='sent'", id);
            });
        }
    }

    private void step(String jobId, int no, String stage, String status, String message) {
        ActiveRun active = activeLeases.get(jobId);
        if (active != null) active.lastProgress.set(System.nanoTime());
        db.update("INSERT INTO create_run_steps(id,job_id,step_no,stage,status,message) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE status=VALUES(status),message=VALUES(message)",
                UUID.randomUUID().toString(), jobId, no, stage, status, message);
    }

    private static final class ActiveRun {
        final String token;
        final Thread owner;
        final RLock lock;
        final AtomicLong lastProgress = new AtomicLong(System.nanoTime());
        ActiveRun(String token, Thread owner, RLock lock) {
            this.token = token; this.owner = owner; this.lock = lock;
        }
    }

    private int nextStepNo(String jobId) {
        return db.queryForObject("SELECT COALESCE(MAX(step_no),0)+1 FROM create_run_steps WHERE job_id=?",
                Integer.class, jobId);
    }

}
