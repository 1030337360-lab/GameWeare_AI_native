package com.gameweare.api.play;

import com.gameweare.api.play.dao.PlayMapper;
import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import com.gameweare.api.catalog.GameTrendingService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.net.URI;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@Service
class PlayService {
    private static final Set<String> EVENTS = Set.of("game_view", "game_start", "game_load_error", "game_end");
    private final PlayMapper plays;
    private final MinioClient minio;
    private final String bucket;
    private final String frameAncestor;
    private final GameTrendingService trending;
    private final PlayUvService uv;

    @org.springframework.beans.factory.annotation.Autowired
    PlayService(PlayMapper plays, MinioClient minio, GameTrendingService trending, PlayUvService uv,
            @Value("${gameweare.minio.bucket:gameweare}") String bucket,
            @Value("${gameweare.web-origin:http://localhost:1314}") String webOrigin) {
        this.plays = plays; this.minio = minio; this.bucket = bucket;
        this.trending = trending; this.uv = uv;
        URI origin = URI.create(webOrigin);
        if (!("http".equalsIgnoreCase(origin.getScheme()) || "https".equalsIgnoreCase(origin.getScheme()))
                || origin.getHost() == null || origin.getUserInfo() != null
                || (origin.getRawPath() != null && !origin.getRawPath().isEmpty()
                        && !"/".equals(origin.getRawPath()))
                || origin.getRawQuery() != null || origin.getRawFragment() != null)
            throw new IllegalArgumentException("gameweare.web-origin must be an HTTP origin");
        this.frameAncestor = origin.getScheme() + "://" + origin.getRawAuthority();
    }

    PlayService(PlayMapper plays, MinioClient minio, String bucket, String webOrigin) {
        this(plays, minio, null, null, bucket, webOrigin);
    }

    public Map<String, Object> manifest(String slug) {
        Map<String, Object> v = plays.publishedVersion(slug);
        if (v == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String documentUrl = "/play/" + slug + "/document";
        return Map.of("id", slug, "title", v.get("title"), "version", String.valueOf(v.get("version_no")),
                "entry", v.get("entry_file") == null ? "index.html" : v.get("entry_file"),
                "bundleUrl", documentUrl, "documentUrl", documentUrl, "assets", List.of(),
                "runtime", v.get("runtime") == null ? "iframe-html5" : v.get("runtime"),
                "sandbox", List.of("allow-scripts"));
    }

    public ResponseEntity<byte[]> document(String slug) {
        Map<String, Object> version = plays.publishedVersion(slug);
        if (version == null || version.get("entry_object_key") == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game document not found");
        String key = version.get("entry_object_key").toString();
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(key).build())) {
            byte[] content = stream.readNBytes(10 * 1024 * 1024 + 1);
            if (content.length > 10 * 1024 * 1024) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Game document too large");
            return ResponseEntity.ok()
                    .contentType(MediaType.TEXT_HTML)
                    .header("Content-Security-Policy", "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; connect-src 'none'; frame-ancestors 'self' " + frameAncestor)
                    .header("X-Content-Type-Options", "nosniff")
                    .header(HttpHeaders.CACHE_CONTROL, "public, max-age=60")
                    .body(content);
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Game document unavailable", e); }
    }

    @Transactional
    public Map<String, Object> event(PlayController.PlayEvent event, String userId) {
        if (event == null || event.gameId() == null || !EVENTS.contains(event.event()))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid play event");
        String gameId = plays.publicGameId(event.gameId());
        if (gameId == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String anonymousId = event.anonymousId();
        if (anonymousId != null && anonymousId.length() > 64) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid anonymousId");
        if (userId != null) anonymousId = null;
        boolean counted = false;
        // A unique row per identity and 30-minute window deduplicates concurrent starts atomically.
        if (("game_view".equals(event.event()) || "game_start".equals(event.event())) && (userId != null || anonymousId != null)) {
            String identity = userId != null ? "u:" + userId : "a:" + anonymousId;
            long windowStartSeconds = (Instant.now().getEpochSecond() / 1800) * 1800;
            counted = plays.countOnce(gameId, identity, Timestamp.from(Instant.ofEpochSecond(windowStartSeconds))) > 0;
        }
        plays.insertEvent(UUID.randomUUID().toString(), userId, anonymousId, gameId, event.event());
        if (counted) plays.incrementPlays(gameId);
        if (trending != null || uv != null) {
            boolean acceptedForUv = "game_view".equals(event.event()) || "game_start".equals(event.event());
            String observedAnonymous = anonymousId;
            boolean updatedCount = counted;
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() {
                    if (updatedCount && trending != null) trending.refresh(gameId);
                    if (acceptedForUv && uv != null) uv.record(gameId, userId, observedAnonymous);
                }
            });
        }
        return Map.of("status", "accepted", "gameId", event.gameId(), "event", event.event(), "counted", counted);
    }

}
