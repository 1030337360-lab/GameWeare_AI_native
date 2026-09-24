package com.gameweare.api.storage;

import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import io.minio.RemoveObjectArgs;
import java.io.IOException;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Uploads are validated (magic bytes) before they reach object storage. */
class UploadServiceTest {
    private static final byte[] PNG = {(byte) 0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0};

    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final MinioClient minio = mock(MinioClient.class);
    private final UploadService service = new UploadService(jdbc, minio, "bucket");

    private MultipartFile file(String mime, byte[] bytes, long size) throws IOException {
        MultipartFile file = mock(MultipartFile.class);
        when(file.isEmpty()).thenReturn(size == 0);
        when(file.getSize()).thenReturn(size);
        when(file.getContentType()).thenReturn(mime);
        when(file.getBytes()).thenReturn(bytes);
        when(file.getOriginalFilename()).thenReturn("cover.png");
        return file;
    }

    @Test
    void rejectsUnsupportedContentType() throws IOException {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.upload(file("text/html", "<html>".getBytes(), 6), "u1"));

        assertEquals(HttpStatus.UNSUPPORTED_MEDIA_TYPE, error.getStatusCode());
    }

    @Test
    void rejectsContentTypeThatDoesNotMatchBytes() throws IOException {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.upload(file("image/png", "not a png".getBytes(), 10), "u1"));

        assertEquals(HttpStatus.UNSUPPORTED_MEDIA_TYPE, error.getStatusCode());
    }

    @Test
    void rejectsOversizedUpload() throws IOException {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.upload(file("image/png", PNG, 10 * 1024 * 1024 + 1), "u1"));

        assertEquals(HttpStatus.PAYLOAD_TOO_LARGE, error.getStatusCode());
    }

    @Test
    void storesPngUploadAndRegistersAsset() throws Exception {
        when(jdbc.update(contains("INSERT INTO assets"), any(Object[].class))).thenReturn(1);

        Map<String, Object> out = service.upload(file("image/png", PNG, PNG.length), "u1");

        assertEquals("uploaded", out.get("status"));
        assertEquals("image/png", out.get("contentType"));
        assertEquals(PNG.length, out.get("size"));
        assertTrue(out.get("objectKey").toString().startsWith("uploads/u1/create-input/"));
        assertTrue(out.get("publicUrl").toString().startsWith("/uploads/"));
        verify(minio).putObject(any(PutObjectArgs.class));
        verify(jdbc).update(contains("INSERT INTO assets"), any(), eq("u1"), eq("bucket"),
                eq(out.get("objectKey")), eq("image/png"), eq(PNG.length), anyString());
    }

    @Test
    void cleansUpObjectWhenAssetRegistrationFails() throws Exception {
        when(jdbc.update(contains("INSERT INTO assets"), any(Object[].class)))
                .thenThrow(new RuntimeException("database unavailable"));

        assertThrows(RuntimeException.class, () -> service.upload(file("image/png", PNG, PNG.length), "u1"));

        verify(minio).putObject(any(PutObjectArgs.class));
        verify(minio).removeObject(any(RemoveObjectArgs.class));
    }
}
