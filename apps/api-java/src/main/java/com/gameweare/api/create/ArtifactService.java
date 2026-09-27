package com.gameweare.api.create;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import io.minio.MinioClient;
import io.minio.PutObjectArgs;

@Service
public class ArtifactService {
    private final JdbcTemplate db;
    private final MinioClient minio;
    private final String bucket;
    private final ArtifactValidator validator;

    public ArtifactService(JdbcTemplate db, MinioClient minio,
                           @Value("${gameweare.minio.bucket}") String bucket, ArtifactValidator validator) {
        this.db = db;
        this.minio = minio;
        this.bucket = bucket;
        this.validator = validator;
    }

    @Transactional
    public Map<String, Object> receive(String userId, ArtifactController.ArtifactRequest request, String key) {
        if (request == null || request.prompt() == null || request.prompt().isBlank() || request.prompt().length() > 4000)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Prompt must be 1 to 4000 characters");
        if (key != null && !key.matches("[A-Za-z0-9._:-]{1,120}"))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid idempotency key");
        ArtifactValidator.Result validation = validator.validate(request.html());
        if (!validation.ok())
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "Artifact failed HTML/JavaScript validation:\n" + ValidationDiagnostics.format(validation.diagnostics()));
        String html = validation.normalizedHtml();
        String digest = sha256(html);
        String requestedProjectId = request.projectId() == null || request.projectId().isBlank() ? null : request.projectId();

        // The user row serializes requests from all API replicas, including identical idempotency keys.
        List<String> owner = db.queryForList("SELECT id FROM users WHERE id=? FOR UPDATE", String.class, userId);
        if (owner.isEmpty()) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "User not found");
        if (key != null) {
            List<Map<String, Object>> previous = db.queryForList(
                    "SELECT id,project_id,game_id,version_id,prompt,artifact_sha256 FROM create_jobs WHERE user_id=? AND idempotency_key=?", userId, key);
            if (!previous.isEmpty()) {
                Map<String, Object> row = previous.get(0);
                if (!request.prompt().equals(row.get("prompt")) || !digest.equals(row.get("artifact_sha256"))
                        || requestedProjectId != null && !requestedProjectId.equals(row.get("project_id")))
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Idempotency key belongs to another artifact");
                return response(row);
            }
        }

        String projectId = requestedProjectId;
        String gameId = null;
        if (projectId == null || projectId.isBlank()) {
            projectId = UUID.randomUUID().toString();
            db.update("INSERT INTO create_projects(id,user_id,title,status,created_at,updated_at) VALUES(?,?,?,'draft',NOW(),NOW())",
                    projectId, userId, CreateService.title(request.prompt()));
        } else {
            List<Map<String, Object>> projects = db.queryForList(
                    "SELECT game_id,status FROM create_projects WHERE id=? AND user_id=? FOR UPDATE", projectId, userId);
            if (projects.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
            if ("archived".equals(projects.get(0).get("status")) || "deleted".equals(projects.get(0).get("status")))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Project is unavailable");
            gameId = (String) projects.get(0).get("game_id");
            Integer active = db.queryForObject("SELECT COUNT(*) FROM create_jobs WHERE project_id=? AND status IN ('pending','generating','planning','reviewing')", Integer.class, projectId);
            if (active != null && active > 0)
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Project has an active generation");
        }
        String jobId = UUID.randomUUID().toString();
        if (gameId == null) gameId = UUID.randomUUID().toString();
        String versionId = UUID.randomUUID().toString();
        String objectKey = "games/" + gameId + "/" + versionId + "/index.html";
        byte[] bytes = html.getBytes(StandardCharsets.UTF_8);
        try {
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(objectKey)
                    .stream(new ByteArrayInputStream(bytes), bytes.length, -1)
                    .contentType("text/html; charset=utf-8").build());
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Could not store artifact", e);
        }
        List<String> existingGame = db.queryForList("SELECT id FROM games WHERE id=? AND author_id=? FOR UPDATE", String.class, gameId, userId);
        boolean newGame = existingGame.isEmpty();
        if (newGame) {
            String title = CreateService.title(request.prompt());
            db.update("INSERT INTO games(id,slug,title,description,author_id,publish_status,visibility,created_at,updated_at) VALUES(?,?,?,?,?,'draft','private',NOW(),NOW())",
                    gameId, "game-" + gameId, title, title, userId);
        }
        int versionNo = db.queryForObject("SELECT COALESCE(MAX(version_no),0)+1 FROM game_versions WHERE game_id=?", Integer.class, gameId);
        db.update("INSERT INTO create_jobs(id,user_id,project_id,prompt,agent_mode,create_type,status,game_id,version_id,idempotency_key,artifact_sha256,reserved_tokens,actual_tokens,created_at,updated_at) VALUES(?,?,?,?,?,'init','completed',?,?,?,?,0,0,NOW(),NOW())",
                jobId, userId, projectId, request.prompt(), "external", gameId, versionId, key, digest);
        db.update("INSERT INTO game_versions(id,game_id,version_no,entry_object_key,runtime,build_status,safety_status,entry_file,storage_prefix,source_job_id) VALUES(?,?,?,?,'iframe-html5','passed','pending','index.html',?,?)",
                versionId, gameId, versionNo, objectKey, "games/" + gameId + "/" + versionId, jobId);
        db.update("INSERT INTO assets(id,owner_id,game_id,version_id,job_id,kind,bucket,object_key,content_type,size_bytes) VALUES(?,?,?,?,?,'html',?,?,?,?)",
                UUID.randomUUID().toString(), userId, gameId, versionId, jobId, bucket, objectKey, "text/html; charset=utf-8", bytes.length);
        if (newGame) db.update("UPDATE games SET current_version_id=?,updated_at=NOW() WHERE id=?", versionId, gameId);
        db.update("UPDATE create_projects SET game_id=?,status='completed',updated_at=NOW() WHERE id=?", gameId, projectId);
        db.update("INSERT INTO create_run_steps(id,job_id,step_no,stage,status,message) VALUES(?,?,1,'compile','completed','Artifact syntax validated')",
                UUID.randomUUID().toString(), jobId);
        return Map.of("jobId", jobId, "projectId", projectId, "gameId", gameId, "versionId", versionId, "status", "completed");
    }

    private Map<String, Object> response(Map<String, Object> row) {
        return Map.of("jobId", row.get("id"), "projectId", row.get("project_id"),
                "gameId", row.get("game_id"), "versionId", row.get("version_id"), "status", "completed");
    }

    private static String sha256(String content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) { throw new IllegalStateException(e); }
    }
}
