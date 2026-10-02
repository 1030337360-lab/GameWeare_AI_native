package com.gameweare.api.storage;

import com.gameweare.api.storage.dao.AssetMapper;
import com.gameweare.api.create.CoverGenerator;
import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class GameCoverController {
    private final AssetMapper assets;
    private final MinioClient minio;
    private final String bucket;

    public GameCoverController(AssetMapper assets, MinioClient minio, @Value("${gameweare.minio.bucket:gameweare}") String bucket) {
        this.assets = assets; this.minio = minio; this.bucket = bucket;
    }

    @GetMapping("/games/{slug}/cover")
    public ResponseEntity<byte[]> cover(@PathVariable String slug) {
        java.util.Map<String, Object> game = assets.publicCover(slug);
        if (game == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game cover not found");
        String key = (String) game.get("cover_object_key");
        if (key == null) {
            String title = String.valueOf(game.get("title"));
            String description = String.valueOf(game.get("description"));
            return ResponseEntity.ok().contentType(MediaType.parseMediaType("image/svg+xml"))
                    .header("Content-Security-Policy", "default-src 'none'; script-src 'none'; object-src 'none'")
                    .header("X-Content-Type-Options", "nosniff")
                    .header(HttpHeaders.CACHE_CONTROL, "public, max-age=3600")
                    .body(CoverGenerator.fallback(title, description));
        }
        String mime = assets.coverContentType(key);
        String type = mime == null ? "image/png" : mime;
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(bucket).object(key).build())) {
            byte[] content = stream.readNBytes(10 * 1024 * 1024 + 1);
            if (content.length > 10 * 1024 * 1024) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Cover too large");
            return ResponseEntity.ok().contentType(MediaType.parseMediaType(type))
                    .header("Content-Security-Policy", "default-src 'none'; script-src 'none'; object-src 'none'")
                    .header("X-Content-Type-Options", "nosniff")
                    .header(HttpHeaders.CACHE_CONTROL, "public, max-age=3600")
                    .body(content);
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Cover unavailable", e); }
    }
}
