package com.gameweare.api.storage;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class GameCoverController {
    private final JdbcTemplate jdbc;
    private final MinioClient minio;
    private final String bucket;

    public GameCoverController(JdbcTemplate jdbc, MinioClient minio, @Value("${gameweare.minio.bucket:gameweare}") String bucket) {
        this.jdbc = jdbc; this.minio = minio; this.bucket = bucket;
    }

    @GetMapping("/games/{slug}/cover")
    public ResponseEntity<byte[]> cover(@PathVariable String slug) {
        List<String> keys = jdbc.queryForList("""
            SELECT cover_object_key FROM games
            WHERE slug=? AND publish_status='published' AND visibility='public' AND cover_object_key IS NOT NULL
            """, String.class, slug);
        if (keys.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game cover not found");
        String key = keys.get(0);
        List<String> mime = jdbc.queryForList("SELECT content_type FROM assets WHERE object_key=? AND kind='cover' LIMIT 1", String.class, key);
        String type = mime.isEmpty() ? "image/png" : mime.get(0);
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(key).build())) {
            byte[] content = stream.readNBytes(10 * 1024 * 1024 + 1);
            if (content.length > 10 * 1024 * 1024) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Cover too large");
            return ResponseEntity.ok().contentType(MediaType.parseMediaType(type))
                    .header("X-Content-Type-Options", "nosniff")
                    .header(HttpHeaders.CACHE_CONTROL, "public, max-age=3600")
                    .body(content);
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Cover unavailable", e); }
    }
}
