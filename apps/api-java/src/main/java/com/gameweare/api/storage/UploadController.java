package com.gameweare.api.storage;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import jakarta.servlet.http.HttpServletRequest;
import java.io.ByteArrayInputStream;
import java.io.IOException;
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
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/uploads")
public class UploadController {
    private final UploadService uploads;

    public UploadController(UploadService uploads) { this.uploads = uploads; }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, Object> upload(@RequestParam("file") MultipartFile file, HttpServletRequest request) {
        return uploads.upload(file, requiredUser(request));
    }

    @DeleteMapping("/{assetId}")
    public Map<String, Object> delete(@PathVariable String assetId, HttpServletRequest request) {
        return uploads.delete(assetId, requiredUser(request));
    }

    @GetMapping("/{assetId}/content")
    public ResponseEntity<byte[]> content(@PathVariable String assetId, HttpServletRequest request) {
        return uploads.content(assetId, requiredUser(request));
    }

    private String requiredUser(HttpServletRequest request) {
        Object id = request.getAttribute("userId");
        if (id == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Login required");
        return id.toString();
    }
}

@Service
class UploadService {
    private static final Set<String> TYPES = Set.of("image/png", "image/jpeg", "image/webp", "image/gif");
    private static final int MAX_UPLOAD = 10 * 1024 * 1024;
    private final JdbcTemplate jdbc;
    private final MinioClient minio;
    private final String bucket;

    UploadService(JdbcTemplate jdbc, MinioClient minio, @Value("${gameweare.minio.bucket:gameweare}") String bucket) {
        this.jdbc = jdbc; this.minio = minio; this.bucket = bucket;
    }

    public Map<String, Object> upload(MultipartFile file, String userId) {
        if (file.isEmpty()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Upload file is empty");
        if (file.getSize() > MAX_UPLOAD) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Upload exceeds 10 MiB");
        String mime = file.getContentType();
        if (!TYPES.contains(mime)) throw new ResponseStatusException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "Unsupported image type");
        byte[] bytes;
        try { bytes = file.getBytes(); }
        catch (IOException e) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Cannot read upload", e); }
        if (!matchesSignature(mime, bytes)) throw new ResponseStatusException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "Image content does not match type");
        String assetId = UUID.randomUUID().toString();
        String extension = switch (mime) { case "image/png" -> "png"; case "image/jpeg" -> "jpg"; case "image/webp" -> "webp"; default -> "gif"; };
        String objectKey = "uploads/" + userId + "/create-input/" + assetId + "/image." + extension;
        try {
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(objectKey)
                    .stream(new ByteArrayInputStream(bytes), bytes.length, -1).contentType(mime).build());
        } catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Object storage unavailable", e); }
        try {
            jdbc.update("""
                INSERT INTO assets(id,owner_id,kind,bucket,object_key,content_type,size_bytes,public_url,created_at)
                VALUES (?,?,'upload',?,?,?,?,?,UTC_TIMESTAMP())
                """, assetId, userId, bucket, objectKey, mime, bytes.length, "/uploads/" + assetId + "/content");
        } catch (RuntimeException e) {
            try { minio.removeObject(RemoveObjectArgs.builder().bucket(bucket).object(objectKey).build()); }
            catch (Exception cleanup) { e.addSuppressed(cleanup); }
            throw e;
        }
        return Map.of("status", "uploaded", "assetId", assetId,
                "filename", file.getOriginalFilename() == null ? "image." + extension : file.getOriginalFilename(),
                "contentType", mime, "size", bytes.length, "objectKey", objectKey,
                "publicUrl", "/uploads/" + assetId + "/content");
    }

    public Map<String, Object> delete(String assetId, String userId) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT bucket,object_key FROM assets WHERE id=? AND owner_id=? AND kind='upload'", assetId, userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Upload not found");
        Map<String, Object> row = rows.get(0);
        try { minio.removeObject(RemoveObjectArgs.builder().bucket(row.get("bucket").toString()).object(row.get("object_key").toString()).build()); }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Object storage unavailable", e); }
        jdbc.update("DELETE FROM assets WHERE id=? AND owner_id=? AND kind='upload'", assetId, userId);
        return Map.of("deleted", true, "assetId", assetId);
    }

    public ResponseEntity<byte[]> content(String assetId, String userId) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT bucket,object_key,content_type FROM assets WHERE id=? AND owner_id=? AND kind='upload'", assetId, userId);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Upload not found");
        Map<String, Object> row = rows.get(0);
        try (var stream = minio.getObject(GetObjectArgs.builder().bucket(row.get("bucket").toString()).object(row.get("object_key").toString()).build())) {
            byte[] data = stream.readNBytes(MAX_UPLOAD + 1);
            if (data.length > MAX_UPLOAD) throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE, "Stored upload too large");
            return ResponseEntity.ok().contentType(MediaType.parseMediaType(row.get("content_type").toString()))
                    .header("X-Content-Type-Options", "nosniff")
                    .header(HttpHeaders.CACHE_CONTROL, "private, max-age=60")
                    .body(data);
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Object storage unavailable", e); }
    }

    private boolean matchesSignature(String mime, byte[] bytes) {
        if ("image/png".equals(mime)) return starts(bytes, new int[]{0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a});
        if ("image/jpeg".equals(mime)) return starts(bytes, new int[]{0xff, 0xd8, 0xff});
        if ("image/gif".equals(mime)) return starts(bytes, new int[]{'G','I','F','8','7','a'}) || starts(bytes, new int[]{'G','I','F','8','9','a'});
        return bytes.length >= 12 && starts(bytes, new int[]{'R','I','F','F'}) &&
                bytes[8]=='W' && bytes[9]=='E' && bytes[10]=='B' && bytes[11]=='P';
    }

    private boolean starts(byte[] bytes, int[] signature) {
        if (bytes.length < signature.length) return false;
        for (int i=0; i<signature.length; i++) if ((bytes[i] & 0xff) != signature[i]) return false;
        return true;
    }
}
