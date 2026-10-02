package com.gameweare.api.create;

import com.gameweare.api.create.dao.ArtifactMapper;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import io.minio.MinioClient;
import io.minio.PutObjectArgs;

@Service
public class ArtifactService {
    private final ArtifactMapper artifacts;
    private final MinioClient minio;
    private final String bucket;
    private final ArtifactValidator validator;

    public ArtifactService(ArtifactMapper artifacts, MinioClient minio,
                           @Value("${gameweare.minio.bucket}") String bucket, ArtifactValidator validator) {
        this.artifacts = artifacts;
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
        if (artifacts.lockUser(userId) == null)
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "User not found");
        if (key != null) {
            Map<String, Object> row = artifacts.existingJob(userId, key);
            if (row != null) {
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
            artifacts.insertProject(projectId, userId, CreateService.title(request.prompt()));
        } else {
            Map<String, Object> project = artifacts.lockProject(projectId, userId);
            if (project == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
            if ("archived".equals(project.get("status")) || "deleted".equals(project.get("status")))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Project is unavailable");
            gameId = (String) project.get("game_id");
            if (artifacts.activeJobCount(projectId) > 0)
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
        boolean newGame = artifacts.ownedGameId(gameId, userId) == null;
        if (newGame) {
            String title = CreateService.title(request.prompt());
            artifacts.insertGame(gameId, "game-" + gameId, title, userId);
        }
        int versionNo = artifacts.nextVersionNo(gameId);
        artifacts.insertJob(jobId, userId, projectId, request.prompt(), gameId, versionId, key, digest);
        artifacts.insertVersion(versionId, gameId, versionNo, objectKey,
                "games/" + gameId + "/" + versionId, jobId);
        artifacts.insertAsset(UUID.randomUUID().toString(), userId, gameId, versionId, jobId,
                bucket, objectKey, "text/html; charset=utf-8", bytes.length);
        if (newGame) artifacts.setCurrentVersion(versionId, gameId);
        artifacts.completeProject(gameId, projectId);
        artifacts.insertCompileStep(UUID.randomUUID().toString(), jobId);
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
