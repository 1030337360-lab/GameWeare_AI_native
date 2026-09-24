package com.gameweare.api.create;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.gameweare.api.billing.TokenBillingService;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;

@Service
public class CreateService {
    static final long RESERVED_TOKENS = 32768;
    private static final ObjectMapper JSON = new ObjectMapper();
    /** Production requires HTTPS providers on public addresses; local stacks may opt in via yahaha.llm.allow-private-endpoints. */
    static volatile boolean privateLlmEndpointsAllowed = false;
    private static final ThreadPoolExecutor SSE_POOL = new ThreadPoolExecutor(8, 64, 60, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(128), task -> {
                Thread thread = new Thread(task, "create-sse"); thread.setDaemon(true); return thread;
            });
    private final JdbcTemplate db;
    private final TokenBillingService billing;
    private final String encryptionSecret;
    private final MinioClient minio;
    private final String bucket;
    private final SecureRandom random = new SecureRandom();

    public CreateService(JdbcTemplate db, TokenBillingService billing, MinioClient minio,
                         @Value("${AI_CONFIG_SECRET:}") String secret,
                         @Value("${yahaha.minio.bucket}") String bucket) {
        this.db = db;
        this.billing = billing;
        this.encryptionSecret = secret;
        this.minio = minio;
        this.bucket = bucket;
    }

    @Value("${yahaha.llm.allow-private-endpoints:false}")
    void configurePrivateLlmEndpoints(boolean allowed) { privateLlmEndpointsAllowed = allowed; }

    @Transactional
    public Map<String, Object> create(String userId, CreateController.JobRequest input, String idempotencyKey) {
        if (idempotencyKey != null) {
            if (idempotencyKey.length() > 120 || !idempotencyKey.matches("[A-Za-z0-9._:-]{1,120}"))
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid idempotency key");
            Map<String, Object> existing = existingRow(userId, idempotencyKey);
            if (existing != null) return checkedExisting(userId, input, existing);
        }
        if (input.prompt().length() > 4000) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Prompt too long");
        if (input.files() != null && !input.files().isEmpty())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Legacy file references are not supported; upload images first");
        if (input.inputAssets() != null && input.inputAssets().size() > 3)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "At most three images are supported");
        String mode = Optional.ofNullable(input.agentMode()).orElse("chat");
        String type = Optional.ofNullable(input.createType()).orElse("init");
        if (!Set.of("chat", "react", "plan", "refine", "decentralized", "init", "opt").contains(mode)
                || !Set.of("init", "opt").contains(type))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid generation mode");
        if (configRow(userId) == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "Configure an AI provider first");
        String projectId = input.projectId();
        String existingGameId = null;
        if (projectId == null || projectId.isBlank()) {
            projectId = UUID.randomUUID().toString();
            db.update("INSERT INTO create_projects(id,user_id,title,status,created_at,updated_at) VALUES(?,?,?,'draft',NOW(),NOW())",
                    projectId, userId, title(input.prompt()));
        } else {
            Map<String, Object> project = one("SELECT game_id FROM create_projects WHERE id=? AND user_id=? FOR UPDATE", projectId, userId);
            if (project == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
            Integer active = db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE project_id=? AND status IN ('pending','generating')", Integer.class, projectId);
            if (active != null && active > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "Project already has an active generation");
            existingGameId = (String) project.get("game_id");
        }
        String id = UUID.randomUUID().toString();
        billing.reserve(userId, id, RESERVED_TOKENS);
        db.update("INSERT INTO create_jobs(id,user_id,project_id,prompt,agent_mode,create_type,status,reserved_tokens,game_id,idempotency_key,created_at,updated_at) VALUES(?,?,?,?,?,?,'pending',?,?,?,NOW(),NOW())",
                id, userId, projectId, input.prompt(), mode, type, RESERVED_TOKENS, existingGameId, idempotencyKey);
        if (input.inputAssets() != null) {
            long totalBytes = 0;
            for (CreateController.InputAsset asset : input.inputAssets()) {
                Map<String, Object> stored = one("SELECT object_key,content_type,size_bytes FROM assets WHERE id=? AND owner_id=? AND kind='upload' FOR UPDATE",
                        asset.assetId(), userId);
                if (stored == null || !Objects.equals(stored.get("object_key"), asset.objectKey())
                        || !Objects.equals(stored.get("content_type"), asset.contentType()))
                    throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Image asset is missing or not owned by this user");
                totalBytes += ((Number) stored.get("size_bytes")).longValue();
                if (totalBytes > 12 * 1024 * 1024) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Images exceed 12 MiB");
                db.update("INSERT INTO create_job_inputs(job_id,asset_id) VALUES(?,?)", id, asset.assetId());
            }
        }
        db.update("INSERT INTO outbox_events(id,aggregate_id,event_type,payload,status,attempts,available_at,created_at) VALUES(?,?,?,?,'pending',0,NOW(),NOW())",
                UUID.randomUUID().toString(), id, "job.created", "{}");
        return job(userId, id);
    }

    public Map<String, Object> existingForKey(String userId, CreateController.JobRequest input, String key) {
        Map<String, Object> row = existingRow(userId, key);
        if (row == null) throw new ResponseStatusException(HttpStatus.CONFLICT, "Concurrent request is still being committed");
        return checkedExisting(userId, input, row);
    }

    private Map<String, Object> existingRow(String userId, String key) {
        return one("SELECT id,prompt,agent_mode,create_type,project_id FROM create_jobs WHERE user_id=? AND idempotency_key=?", userId, key);
    }

    private Map<String, Object> checkedExisting(String userId, CreateController.JobRequest input, Map<String, Object> row) {
        List<String> requestedAssets = input.inputAssets() == null ? List.of()
                : input.inputAssets().stream().map(CreateController.InputAsset::assetId).sorted().toList();
        List<String> storedAssets = db.queryForList("SELECT asset_id FROM create_job_inputs WHERE job_id=? ORDER BY asset_id", String.class, row.get("id"));
        if (input.files() != null && !input.files().isEmpty() || !requestedAssets.equals(storedAssets)
                || !Objects.equals(input.prompt(), row.get("prompt"))
                || !Objects.equals(Optional.ofNullable(input.agentMode()).orElse("chat"), row.get("agent_mode"))
                || !Objects.equals(Optional.ofNullable(input.createType()).orElse("init"), row.get("create_type"))
                || input.projectId() != null && !Objects.equals(input.projectId(), row.get("project_id")))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Idempotency key was used for another request");
        return job(userId, (String) row.get("id"));
    }

    public Map<String, Object> job(String userId, String id) {
        Map<String, Object> row = one("SELECT * FROM create_jobs WHERE id=? AND user_id=?", id, userId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Job not found");
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("id", id);
        result.put("status", row.get("status"));
        result.put("prompt", row.get("prompt"));
        result.put("createdAt", row.get("created_at"));
        result.put("agentMode", row.get("agent_mode"));
        result.put("createType", row.get("create_type"));
        result.put("projectId", row.get("project_id"));
        result.put("runId", id);
        result.put("gameId", row.get("game_id"));
        result.put("versionId", row.get("version_id"));
        result.put("errorMessage", row.get("error_message"));
        result.put("logs", steps(userId, id, 0).stream().map(s -> Map.of("stage", s.get("stage"), "status", s.get("status"), "message", s.get("message"))).toList());
        if (row.get("game_id") != null) {
            Map<String, Object> game = one("SELECT slug,publish_status,visibility FROM games WHERE id=?", row.get("game_id"));
            if (game != null) {
                result.put("gameSlug", game.get("slug"));
                result.put("publishStatus", game.get("publish_status"));
                result.put("visibility", game.get("visibility"));
                result.put("playUrl", "/games/" + game.get("slug") + "/play");
            }
        }
        return result;
    }

    @Transactional
    public Map<String, Object> publish(String userId, String id) {
        Map<String, Object> row = one("SELECT game_id,status FROM create_jobs WHERE id=? AND user_id=?", id, userId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Job not found");
        if (!"completed".equals(row.get("status")) || row.get("game_id") == null)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Generation has not completed");
        db.update("UPDATE games SET publish_status='published',visibility='public',published_at=NOW(),updated_at=NOW() WHERE id=? AND author_id=?",
                row.get("game_id"), userId);
        return job(userId, id);
    }

    public List<Map<String, Object>> projects(String userId) {
        return db.query("SELECT * FROM create_projects WHERE user_id=? ORDER BY created_at DESC LIMIT 100", (rs, n) -> projectMap(rs.getString("id"), rs.getString("title"), rs.getString("status"), rs.getString("game_id"), rs.getTimestamp("created_at"), rs.getTimestamp("updated_at")), userId);
    }

    public Map<String, Object> project(String userId, String id) {
        Map<String, Object> row = one("SELECT * FROM create_projects WHERE id=? AND user_id=?", id, userId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
        return projectMap(id, (String) row.get("title"), (String) row.get("status"), (String) row.get("game_id"), row.get("created_at"), row.get("updated_at"));
    }

    @Transactional
    public Map<String, Object> deleteProject(String userId, String id) {
        Map<String, Object> project = one("SELECT game_id FROM create_projects WHERE id=? AND user_id=? FOR UPDATE", id, userId);
        if (project == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
        Integer active = db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE project_id=? AND status IN ('pending','generating')", Integer.class, id);
        if (active != null && active > 0) throw new ResponseStatusException(HttpStatus.CONFLICT, "Project has an active generation");
        db.update("UPDATE create_projects SET status='archived',updated_at=NOW() WHERE id=?", id);
        return Map.of("projectId", id, "deleted", true);
    }

    public Map<String, Object> preview(String userId, String id) {
        Map<String, Object> row = one("SELECT g.id game_id,g.slug,g.title,g.description,v.id version_id,v.version_no,v.entry_object_key "
                + "FROM create_projects p JOIN games g ON g.id=p.game_id JOIN game_versions v ON v.id=g.current_version_id "
                + "WHERE p.id=? AND p.user_id=?", id, userId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project preview not found");
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object((String) row.get("entry_object_key")).build())) {
            String html = new String(stream.readNBytes(2_000_001), StandardCharsets.UTF_8);
            if (html.length() > 2_000_000) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Preview too large");
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("projectId", id); out.put("gameId", row.get("game_id")); out.put("gameSlug", row.get("slug"));
            out.put("title", row.get("title")); out.put("description", row.get("description"));
            out.put("versionId", row.get("version_id")); out.put("versionNo", row.get("version_no"));
            out.put("entryFile", "index.html"); out.put("html", html); out.put("source", Map.of());
            return out;
        } catch (ResponseStatusException ex) { throw ex; }
        catch (Exception ex) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Could not load preview"); }
    }

    public Map<String, Object> recentGame(String userId) {
        Map<String, Object> row = one("SELECT j.id job_id,g.id game_id,g.slug,g.title FROM create_jobs j JOIN games g ON g.id=j.game_id "
                + "WHERE j.user_id=? AND j.status='completed' ORDER BY j.created_at DESC LIMIT 1", userId);
        if (row == null) return null;
        return Map.of("gameId", row.get("game_id"), "gameSlug", row.get("slug"), "title", row.get("title"),
                "playUrl", "/games/" + row.get("slug") + "/play", "jobId", row.get("job_id"));
    }

    private Map<String, Object> projectMap(String id, String title, String status, String gameId, Object created, Object updated) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("projectId", id); value.put("title", title); value.put("status", status);
        value.put("gameId", gameId); value.put("createdAt", created); value.put("updatedAt", updated);
        if (gameId != null) {
            Map<String, Object> game = one("SELECT slug,publish_status,visibility FROM games WHERE id=?", gameId);
            if (game != null) { value.put("gameSlug", game.get("slug")); value.put("publishStatus", game.get("publish_status")); value.put("visibility", game.get("visibility")); }
        }
        return value;
    }

    public List<Map<String, Object>> steps(String userId, String jobId, int afterStep) {
        if (db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE id=? AND user_id=?", Integer.class, jobId, userId) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Run not found");
        return db.query("SELECT step_no,stage,status,message,created_at FROM create_run_steps WHERE job_id=? AND step_no>? ORDER BY step_no",
                (rs, n) -> Map.of("runId", jobId, "stepNo", rs.getInt("step_no"), "stage", rs.getString("stage"), "status", rs.getString("status"), "message", rs.getString("message"), "createdAt", rs.getTimestamp("created_at")), jobId, afterStep);
    }

    // ---------- advanced agent workflows (plan and decentralized modes) ----------

    public Map<String, Object> planPreview(String userId, String id) {
        requireMode(userId, id, "plan");
        Map<String, Object> workflow = workflowRow(id);
        if (workflow == null || workflow.get("preview_json") == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Plan preview not found");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("runId", id);
        out.put("jobId", id);
        out.put("phase", workflow.get("phase"));
        out.put("planPreview", readTree((String) workflow.get("preview_json")));
        return out;
    }

    @Transactional
    public Map<String, Object> planDecision(String userId, String id, String decision) {
        String choice = decision(decision);
        Map<String, Object> job = requireMode(userId, id, "plan");
        Map<String, Object> workflow = workflowRow(id);
        if (workflow == null || !"awaiting_plan".equals(workflow.get("phase")))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for plan approval");
        if ("rejected".equals(choice)) {
            int canceled = db.update("UPDATE create_jobs SET status='canceled',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='planning'", id);
            if (canceled != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for plan approval");
            db.update("UPDATE create_job_workflows SET phase='rejected' WHERE job_id=?", id);
            step(id, 3, "plan_rejected", "completed", "Plan rejected by user; run canceled and kept for review");
            if ("init".equals(job.get("create_type")) && job.get("game_id") == null)
                db.update("UPDATE create_projects SET status='deleted',updated_at=NOW() WHERE id=? AND game_id IS NULL", job.get("project_id"));
            billing.refund(userId, id);
        } else {
            int resumed = db.update("UPDATE create_jobs SET status='pending',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='planning'", id);
            if (resumed != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for plan approval");
            db.update("UPDATE create_job_workflows SET phase='approved' WHERE job_id=?", id);
            step(id, 3, "plan_accepted", "completed", "Plan accepted; continuing generation");
            redispatch(id);
        }
        return job(userId, id);
    }

    public Map<String, Object> decentralizedPreviews(String userId, String id) {
        requireMode(userId, id, "decentralized");
        return decentralizedState(id);
    }

    @Transactional
    public Map<String, Object> selectCandidate(String userId, String id, String candidateId) {
        requireMode(userId, id, "decentralized");
        Map<String, Object> workflow = workflowRow(id);
        if (workflow == null || workflow.get("preview_json") == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Decentralized previews not found");
        String phase = String.valueOf(workflow.get("phase"));
        if (!"awaiting_selection".equals(phase) && !"candidate_selected".equals(phase))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for candidate selection");
        if (candidateId == null || candidateId.isBlank() || findCandidate((String) workflow.get("preview_json"), candidateId) == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Candidate not found");
        db.update("UPDATE create_job_workflows SET selected_candidate_id=?,phase='candidate_selected' WHERE job_id=?", candidateId, id);
        return decentralizedState(id);
    }

    @Transactional
    public Map<String, Object> confirmCandidate(String userId, String id, String decision) {
        String choice = decision(decision);
        requireMode(userId, id, "decentralized");
        Map<String, Object> workflow = workflowRow(id);
        if (workflow == null)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for candidate selection");
        if ("rejected".equals(choice)) {
            int canceled = db.update("UPDATE create_jobs SET status='canceled',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='reviewing'", id);
            if (canceled != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for candidate selection");
            db.update("UPDATE create_job_workflows SET phase='rejected' WHERE job_id=?", id);
            step(id, 3, "decentralized_rejected", "completed", "Directions rejected by user; run canceled and kept for review");
            billing.refund(userId, id);
        } else {
            if (!"candidate_selected".equals(workflow.get("phase")))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Select a preview candidate before confirming");
            String selected = findCandidate((String) workflow.get("preview_json"), String.valueOf(workflow.get("selected_candidate_id")));
            if (selected == null)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Select a preview candidate before confirming");
            int resumed = db.update("UPDATE create_jobs SET status='pending',lease_token=NULL,lease_expires_at=NULL,updated_at=NOW() WHERE id=? AND status='reviewing'", id);
            if (resumed != 1) throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not waiting for candidate selection");
            db.update("UPDATE create_job_workflows SET phase='approved',preview_json=? WHERE job_id=?", selected, id);
            step(id, 3, "decentralized_confirmed", "completed", "Direction confirmed; final generation is starting");
            redispatch(id);
        }
        return job(userId, id);
    }

    private Map<String, Object> requireMode(String userId, String id, String mode) {
        Map<String, Object> row = one("SELECT agent_mode,status,project_id,create_type,game_id FROM create_jobs WHERE id=? AND user_id=?", id, userId);
        if (row == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Run not found");
        if (!mode.equals(row.get("agent_mode")))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Run is not a " + mode + " strategy run");
        return row;
    }

    private Map<String, Object> workflowRow(String jobId) {
        List<Map<String, Object>> rows = db.queryForList("SELECT phase,preview_json,selected_candidate_id FROM create_job_workflows WHERE job_id=?", jobId);
        return rows.isEmpty() ? null : rows.get(0);
    }

    private Map<String, Object> decentralizedState(String id) {
        Map<String, Object> workflow = workflowRow(id);
        if (workflow == null || workflow.get("preview_json") == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Decentralized previews not found");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("runId", id);
        out.put("jobId", id);
        out.put("phase", workflow.get("phase"));
        out.put("selectedCandidateId", workflow.get("selected_candidate_id"));
        out.put("candidates", candidatesOf((String) workflow.get("preview_json")));
        return out;
    }

    private static String decision(String input) {
        String normalized = input == null ? "" : input.strip().toLowerCase(Locale.ROOT);
        if (!Set.of("accepted", "rejected").contains(normalized))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Decision must be accepted or rejected");
        return normalized;
    }

    /** Plain Java structures so response bodies serialize under the default Jackson 3 converter. */
    private static Object readTree(String json) {
        try { return JSON.readValue(json, Object.class); }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Stored workflow preview is invalid"); }
    }

    @SuppressWarnings("unchecked")
    private static List<Object> candidatesOf(String previewJson) {
        Object parsed = readTree(previewJson);
        return parsed instanceof Map<?, ?> map && map.get("candidates") instanceof List<?> list
                ? (List<Object>) list : List.of();
    }

    private static JsonNode parse(String json) {
        try { return JSON.readTree(json); }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Stored workflow preview is invalid"); }
    }

    private static String findCandidate(String previewJson, String candidateId) {
        if (candidateId == null) return null;
        for (JsonNode candidate : parse(previewJson).path("candidates"))
            if (candidate.path("candidateId").asText("").equals(candidateId)) return candidate.toString();
        return null;
    }

    private void redispatch(String jobId) {
        // uq_outbox_aggregate_type keeps one row per job event forever, so a creator decision
        // re-queues the original row instead of inserting a duplicate that would violate the key.
        db.update("INSERT INTO outbox_events(id,aggregate_id,event_type,payload,status,attempts,available_at,created_at) VALUES(?,?,?,?,'pending',0,NOW(),NOW()) ON DUPLICATE KEY UPDATE status='pending',attempts=0,available_at=NOW(),sending_at=NULL,sent_at=NULL",
                UUID.randomUUID().toString(), jobId, "job.created", "{}");
    }

    private void step(String jobId, int no, String stage, String status, String message) {
        db.update("INSERT INTO create_run_steps(id,job_id,step_no,stage,status,message) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE status=VALUES(status),message=VALUES(message)",
                UUID.randomUUID().toString(), jobId, no, stage, status, message);
    }


    public SseEmitter events(String userId, String id, int afterStep) {
        steps(userId, id, afterStep);
        SseEmitter emitter = new SseEmitter(120_000L);
        try { SSE_POOL.execute(() -> {
            int cursor = Math.max(0, afterStep);
            try {
                for (int i = 0; i < 120; i++) {
                    for (Map<String, Object> step : steps(userId, id, cursor)) {
                        cursor = (int) step.get("stepNo");
                        String event = "failed".equals(step.get("status")) ? "error" : "completed".equals(step.get("status")) ? "done" : "step";
                        emitter.send(SseEmitter.event().id(Integer.toString(cursor)).name(event).data(step));
                    }
                    String status = (String) job(userId, id).get("status");
                    if (Set.of("completed", "failed", "canceled").contains(status)) break;
                    Thread.sleep(1000);
                }
                emitter.complete();
            } catch (Exception e) { emitter.completeWithError(e); }
        }); } catch (java.util.concurrent.RejectedExecutionException busy) {
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "Too many live event streams");
        }
        return emitter;
    }

    public Map<String, Object> config(String userId) {
        Map<String, Object> row = configRow(userId);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("authenticated", true); out.put("configured", row != null); out.put("staticGeneration", false);
        if (row != null) { out.put("baseUrl", row.get("base_url")); out.put("model", row.get("model")); out.put("provider", row.get("provider")); }
        return out;
    }

    @Transactional
    public Map<String, Object> saveConfig(String userId, CreateController.ConfigRequest input) {
        validateBaseUrl(input.baseUrl());
        if (input.model().length() > 200 || input.apiKey().length() > 1000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Configuration field too long");
        String encrypted = encrypt(input.apiKey());
        db.update("INSERT INTO ai_configs(user_id,base_url,model,api_key_ciphertext,provider,updated_at) VALUES(?,?,?,?,?,NOW()) ON DUPLICATE KEY UPDATE base_url=VALUES(base_url),model=VALUES(model),api_key_ciphertext=VALUES(api_key_ciphertext),provider=VALUES(provider),updated_at=NOW()",
                userId, input.baseUrl().trim(), input.model().trim(), encrypted, Optional.ofNullable(input.provider()).orElse("openai"));
        return config(userId);
    }

    public Map<String, Object> testConfig(String userId, CreateController.ConfigTestRequest input) {
        Map<String, Object> saved = configRow(userId);
        String base = input != null && input.baseUrl() != null ? input.baseUrl() : saved == null ? null : (String) saved.get("base_url");
        String model = input != null && input.model() != null ? input.model() : saved == null ? null : (String) saved.get("model");
        String key = input != null && input.apiKey() != null ? input.apiKey() : saved == null ? null : decrypt((String) saved.get("api_key_ciphertext"));
        if (base == null || model == null || key == null) return Map.of("ok", false, "code", "missing_config", "message", "Configure the AI provider first.", "details", Map.of());
        try {
            LlmClient.Result response = LlmClient.generate(base, model, key, "Return a one-word greeting.");
            return Map.of("ok", true, "code", "ok", "message", "Connection successful.", "details", Map.of("totalTokens", response.totalTokens()));
        } catch (Exception ex) {
            return Map.of("ok", false, "code", "provider_error", "message", "AI provider connection failed.", "details", Map.of());
        }
    }

    Map<String, Object> configRow(String userId) { return one("SELECT * FROM ai_configs WHERE user_id=?", userId); }
    private Map<String, Object> one(String sql, Object... args) {
        try { return db.queryForMap(sql, args); } catch (EmptyResultDataAccessException e) { return null; }
    }

    static String title(String prompt) { String s = prompt.strip(); return s.length() <= 80 ? s : s.substring(0, 80); }
    static void validateBaseUrl(String input) {
        try {
            java.net.URI uri = java.net.URI.create(input.strip());
            if (uri.getHost() == null || uri.getUserInfo() != null || uri.getFragment() != null)
                throw new IllegalArgumentException();
            if (!privateLlmEndpointsAllowed && !"https".equalsIgnoreCase(uri.getScheme()))
                throw new IllegalArgumentException();
        } catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "baseUrl must be a valid HTTPS URL"); }
    }

    private SecretKeySpec aesKey() {
        if (encryptionSecret == null || encryptionSecret.length() < 32)
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "AI_CONFIG_SECRET must be at least 32 characters");
        try { return new SecretKeySpec(MessageDigest.getInstance("SHA-256").digest(encryptionSecret.getBytes(StandardCharsets.UTF_8)), "AES"); }
        catch (Exception e) { throw new IllegalStateException(e); }
    }

    String encrypt(String plain) {
        try {
            byte[] nonce = new byte[12]; random.nextBytes(nonce);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, aesKey(), new GCMParameterSpec(128, nonce));
            byte[] encrypted = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            byte[] full = new byte[nonce.length + encrypted.length];
            System.arraycopy(nonce, 0, full, 0, nonce.length); System.arraycopy(encrypted, 0, full, nonce.length, encrypted.length);
            return Base64.getEncoder().encodeToString(full);
        } catch (Exception e) { throw new IllegalStateException("Could not encrypt AI key", e); }
    }

    String decrypt(String encoded) {
        try {
            byte[] full = Base64.getDecoder().decode(encoded);
            byte[] nonce = Arrays.copyOfRange(full, 0, 12);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, aesKey(), new GCMParameterSpec(128, nonce));
            return new String(cipher.doFinal(full, 12, full.length - 12), StandardCharsets.UTF_8);
        } catch (Exception e) { throw new IllegalStateException("Could not decrypt AI key", e); }
    }
}
