package com.gameweare.api.play;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
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
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class PlayController {
    private final PlayService play;

    public PlayController(PlayService play) { this.play = play; }

    @GetMapping("/play/{id}/manifest")
    public Map<String, Object> manifest(@PathVariable String id) { return play.manifest(id); }

    @GetMapping("/play/{id}/document")
    public ResponseEntity<byte[]> document(@PathVariable String id) { return play.document(id); }

    @PostMapping({"/events/play", "/play/events"})
    public Map<String, Object> event(@RequestBody PlayEvent event, HttpServletRequest request) {
        Object userId = request.getAttribute("userId");
        return play.event(event, userId == null ? null : userId.toString());
    }

    public record PlayEvent(String gameId, String event, String anonymousId, Instant occurredAt,
                            Long durationMs, String errorMessage, Map<String, Object> metadata) {}
}

@Service
class PlayService {
    private static final Set<String> EVENTS = Set.of("game_view", "game_start", "game_load_error", "game_end");
    private final JdbcTemplate jdbc;
    private final MinioClient minio;
    private final String bucket;

    PlayService(JdbcTemplate jdbc, MinioClient minio, @Value("${gameweare.minio.bucket:gameweare}") String bucket) {
        this.jdbc = jdbc; this.minio = minio; this.bucket = bucket;
    }

    public Map<String, Object> manifest(String slug) {
        List<Map<String, Object>> rows = publishedVersion(slug);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        Map<String, Object> v = rows.get(0);
        String documentUrl = "/play/" + slug + "/document";
        return Map.of("id", slug, "title", v.get("title"), "version", String.valueOf(v.get("version_no")),
                "entry", v.get("entry_file") == null ? "index.html" : v.get("entry_file"),
                "bundleUrl", documentUrl, "documentUrl", documentUrl, "assets", List.of(),
                "runtime", v.get("runtime") == null ? "iframe-html5" : v.get("runtime"),
                "sandbox", List.of("allow-scripts"));
    }

    public ResponseEntity<byte[]> document(String slug) {
        List<Map<String, Object>> rows = publishedVersion(slug);
        if (rows.isEmpty() || rows.get(0).get("entry_object_key") == null)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game document not found");
        String key = rows.get(0).get("entry_object_key").toString();
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(key).build())) {
            byte[] content = stream.readNBytes(10 * 1024 * 1024 + 1);
            if (content.length > 10 * 1024 * 1024) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Game document too large");
            return ResponseEntity.ok()
                    .contentType(MediaType.TEXT_HTML)
                    .header("Content-Security-Policy", "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; connect-src 'none'; frame-ancestors 'self'")
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
        List<String> ids = jdbc.queryForList("SELECT id FROM games WHERE slug=? AND publish_status='published' AND visibility='public'", String.class, event.gameId());
        if (ids.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String gameId = ids.get(0);
        String anonymousId = event.anonymousId();
        if (anonymousId != null && anonymousId.length() > 64) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid anonymousId");
        if (userId != null) anonymousId = null;
        boolean counted = false;
        // A unique row per identity and 30-minute window deduplicates concurrent starts atomically.
        if (("game_view".equals(event.event()) || "game_start".equals(event.event())) && (userId != null || anonymousId != null)) {
            String identity = userId != null ? "u:" + userId : "a:" + anonymousId;
            long windowStartSeconds = (Instant.now().getEpochSecond() / 1800) * 1800;
            counted = jdbc.update("INSERT IGNORE INTO play_count_dedupe(game_id,identity_key,window_start) VALUES (?,?,?)",
                    gameId, identity, Timestamp.from(Instant.ofEpochSecond(windowStartSeconds))) > 0;
        }
        jdbc.update("INSERT INTO play_events(id,user_id,anonymous_id,game_id,event_type,created_at) VALUES (?,?,?,?,?,UTC_TIMESTAMP())",
                UUID.randomUUID().toString(), userId, anonymousId, gameId, event.event());
        if (counted) jdbc.update("UPDATE games SET plays_count=plays_count+1 WHERE id=?", gameId);
        return Map.of("status", "accepted", "gameId", event.gameId(), "event", event.event(), "counted", counted);
    }

    private List<Map<String, Object>> publishedVersion(String slug) {
        return jdbc.queryForList("""
            SELECT g.title, v.version_no, v.runtime, v.entry_file, v.entry_object_key
            FROM games g JOIN game_versions v ON v.id=g.current_version_id
            WHERE g.slug=? AND g.publish_status='published' AND g.visibility='public' LIMIT 1
            """, slug);
    }
}
