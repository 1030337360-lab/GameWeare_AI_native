package com.gameweare.api.create;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.gameweare.api.billing.TokenBillingService;
import com.gameweare.api.config.InfrastructureConfig;
import io.minio.MinioClient;
import io.minio.GetObjectArgs;
import io.minio.PutObjectArgs;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.UUID;
import java.util.List;
import java.util.ArrayList;
import java.util.Base64;
import java.util.concurrent.ConcurrentHashMap;

@Component
public class CreateWorker {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final JdbcTemplate db;
    private final TransactionTemplate tx;
    private final CreateService service;
    private final TokenBillingService billing;
    private final MinioClient minio;
    private final String bucket;
    private final Map<String, String> activeLeases = new ConcurrentHashMap<>();

    public CreateWorker(JdbcTemplate db, TransactionTemplate tx, CreateService service, TokenBillingService billing,
                        MinioClient minio, @Value("${yahaha.minio.bucket}") String bucket) {
        this.db = db; this.tx = tx; this.service = service; this.billing = billing; this.minio = minio; this.bucket = bucket;
    }

    @RabbitListener(queues = InfrastructureConfig.CREATE_QUEUE)
    public void consume(String jobId) {
        String leaseToken = UUID.randomUUID().toString();
        Map<String, Object> job = tx.execute(s -> {
            int changed = db.update("UPDATE create_jobs SET status='generating',lease_token=?,lease_expires_at=DATE_ADD(NOW(), INTERVAL 10 MINUTE),attempts=attempts+1,updated_at=NOW() WHERE id=? AND status='pending' AND attempts<3",
                    leaseToken, jobId);
            if (changed != 1) return null;
            step(jobId, 1, "generation", "running", "Generating game with configured AI provider");
            return db.queryForMap("SELECT * FROM create_jobs WHERE id=?", jobId);
        });
        if (job == null) return;
        activeLeases.put(jobId, leaseToken);
        String userId = (String) job.get("user_id");
        try {
            Map<String, Object> config = service.configRow(userId);
            if (config == null) throw new IllegalStateException("AI provider configuration is missing");
            String prompt = "Create a complete playable single-file HTML5 browser game. "
                    + "Return only HTML beginning with <!doctype html> and containing inline CSS and JavaScript. "
                    + "Do not load external scripts or assets. Game request: " + job.get("prompt");
            if (job.get("game_id") != null && "opt".equals(job.get("create_type"))) {
                var versions = db.queryForList("SELECT v.entry_object_key FROM game_versions v JOIN games g ON g.current_version_id=v.id WHERE g.id=? AND g.author_id=?",
                        job.get("game_id"), userId);
                if (!versions.isEmpty()) {
                    String existingKey = (String) versions.get(0).get("entry_object_key");
                    try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(existingKey).build())) {
                        String previous = new String(stream.readNBytes(24_000), StandardCharsets.UTF_8);
                        prompt += "\nImprove the existing game and preserve working features. Existing HTML:\n" + previous;
                    }
                }
            }
            List<LlmClient.Image> images = loadImages(userId, jobId);
            Map<String, Object> workflow = workflow(jobId);
            String mode = (String) job.get("agent_mode");
            if (workflow == null && ("plan".equals(mode) || "decentralized".equals(mode))) {
                prepareApproval(jobId, userId, leaseToken, config, mode, prompt, images);
                return;
            }
            if (workflow != null && "approved".equals(workflow.get("phase"))) {
                String preview = (String) workflow.get("preview_json");
                prompt += "\nThe creator approved this direction. Follow it exactly:\n" + preview;
            }
            if ("react".equals(mode)) {
                if (workflow == null) {
                    LlmClient.Result reflection = LlmClient.generate((String) config.get("base_url"), (String) config.get("model"),
                            service.decrypt((String) config.get("api_key_ciphertext")),
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
            LlmClient.Result generated = LlmClient.generate((String) config.get("base_url"), (String) config.get("model"),
                    service.decrypt((String) config.get("api_key_ciphertext")), prompt, images);
            String html = validateHtml(generated.text());
            long previousTokens = workflow == null ? 0 : ((Number) workflow.get("used_tokens")).longValue();
            long previousPrompt = workflow == null ? 0 : ((Number) workflow.get("prompt_tokens")).longValue();
            long previousCompletion = workflow == null ? 0 : ((Number) workflow.get("completion_tokens")).longValue();
            long totalTokens = Math.addExact(previousTokens, generated.totalTokens());
            // Steps: 1 running, 2 preview/reason ready, 3 creator decision (approval workflows), 4 final generation.
            int finalStepNo = workflow != null && "approved".equals(workflow.get("phase")) ? 4 : workflow == null ? 2 : 3;
            if (totalTokens > CreateService.RESERVED_TOKENS)
                throw new IllegalStateException("Provider token usage exceeded reservation");
            String gameId = job.get("game_id") == null ? UUID.randomUUID().toString() : (String) job.get("game_id");
            String versionId = UUID.randomUUID().toString();
            String key = "games/" + gameId + "/" + versionId + "/index.html";
            byte[] bytes = html.getBytes(StandardCharsets.UTF_8);
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(key)
                    .stream(new ByteArrayInputStream(bytes), bytes.length, -1).contentType("text/html; charset=utf-8").build());
            tx.executeWithoutResult(s -> {
                Map<String, Object> current = db.queryForMap("SELECT status,lease_token FROM create_jobs WHERE id=? FOR UPDATE", jobId);
                if (!"generating".equals(current.get("status")) || !leaseToken.equals(current.get("lease_token"))) return;
                String title = CreateService.title((String) job.get("prompt"));
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
                db.update("UPDATE games SET current_version_id=?,updated_at=NOW() WHERE id=?", versionId, gameId);
                db.update("UPDATE create_projects SET game_id=?,status='completed',updated_at=NOW() WHERE id=?", gameId, job.get("project_id"));
                db.update("UPDATE create_jobs SET game_id=?,version_id=?,actual_tokens=?,status='completed',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=?",
                        gameId, versionId, totalTokens, jobId);
                db.update("INSERT INTO model_usage_events(id,job_id,provider,model,prompt_tokens,completion_tokens,total_tokens) VALUES(?,?,?,?,?,?,?)",
                        UUID.randomUUID().toString(), jobId, config.get("provider"), config.get("model"),
                        previousPrompt + generated.promptTokens(), previousCompletion + generated.completionTokens(), totalTokens);
                step(jobId, finalStepNo, "generation", "completed", "Game generated and stored");
                billing.settle(userId, jobId, totalTokens);
            });
        } catch (Exception ex) {
            tx.executeWithoutResult(s -> {
                int changed = db.update("UPDATE create_jobs SET status='failed',lease_token=NULL,lease_expires_at=NULL,error_message=?,updated_at=NOW() WHERE id=? AND status='generating' AND lease_token=?",
                        safeError(ex), jobId, leaseToken);
                if (changed == 1) {
                    step(jobId, 4, "generation", "failed", safeError(ex));
                    billing.refund(userId, jobId);
                }
            });
        } finally { activeLeases.remove(jobId, leaseToken); }
    }

    private Map<String, Object> workflow(String jobId) {
        var rows = db.queryForList("SELECT phase,preview_json,selected_candidate_id,prompt_tokens,completion_tokens,used_tokens FROM create_job_workflows WHERE job_id=?", jobId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private boolean leaseOwned(String jobId, String token) {
        Integer count = db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE id=? AND status='generating' AND lease_token=?", Integer.class, jobId, token);
        return count != null && count == 1;
    }

    private void prepareApproval(String jobId, String userId, String leaseToken, Map<String, Object> config,
                                 String mode, String prompt, List<LlmClient.Image> images) throws Exception {
        String instruction = "plan".equals(mode)
                ? "Return ONLY JSON object with plan (3-8 objects with id,title,goal,toolFamily,expectedOutput,acceptanceCheckRefs), risks (nonempty strings), acceptanceChecks (objects with id,description,type,severity). Plan this playable HTML5 game. Request: "
                : "Return ONLY JSON object with candidates: exactly 3 distinct objects, each with candidateId,title,conceptSummary,expertRole,expertDomain,expertIntro,styleTags (array),staticHtml (a self-contained simple HTML visual preview). Request: ";
        LlmClient.Result result = LlmClient.generate((String) config.get("base_url"), (String) config.get("model"),
                service.decrypt((String) config.get("api_key_ciphertext")), instruction + prompt, images);
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
        activeLeases.forEach((jobId, token) -> db.update("UPDATE create_jobs SET lease_expires_at=DATE_ADD(NOW(), INTERVAL 10 MINUTE) WHERE id=? AND status='generating' AND lease_token=?",
                jobId, token));
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
                    if (changed == 1) { step(id, 4, "generation", "failed", "Worker lease expired after retries"); billing.refund(userId, id); }
                } else {
                    int changed = db.update("UPDATE create_jobs SET status='pending',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='generating' AND lease_expires_at<NOW()", id);
                    if (changed == 1) db.update("UPDATE outbox_events SET status='pending',available_at=NOW() WHERE aggregate_id=? AND event_type='job.created'", id);
                }
            });
        }
    }

    private void step(String jobId, int no, String stage, String status, String message) {
        db.update("INSERT INTO create_run_steps(id,job_id,step_no,stage,status,message) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE status=VALUES(status),message=VALUES(message)",
                UUID.randomUUID().toString(), jobId, no, stage, status, message);
    }

    static String validateHtml(String raw) {
        String html = raw.strip().replaceFirst("(?is)^```(?:html)?\\s*", "").replaceFirst("(?s)\\s*```$", "").strip();
        String lower = html.toLowerCase(java.util.Locale.ROOT);
        if (html.length() < 100 || html.length() > 2_000_000 || !lower.contains("<html") || !lower.contains("</html>")
                || !lower.contains("<script") || lower.contains("<script src=") || lower.contains("http://") || lower.contains("https://"))
            throw new IllegalStateException("AI response is not a self-contained playable HTML game");
        return html;
    }

    private String safeError(Exception ex) {
        if (ex instanceof IllegalStateException) {
            String message = ex.getMessage();
            if (message != null && !message.contains("key") && !message.contains("Bearer")) return message.substring(0, Math.min(300, message.length()));
        }
        return "Game generation failed. Check AI configuration and retry.";
    }
}
