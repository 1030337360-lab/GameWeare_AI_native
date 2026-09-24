package com.gameweare.api.create;

import com.gameweare.api.billing.TokenBillingService;
import io.minio.MinioClient;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Input validation and AI-config handling in CreateService. */
class CreateServiceValidationTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final CreateService service = new CreateService(db, mock(TokenBillingService.class),
            mock(MinioClient.class), "test-secret-that-is-32-chars-long", "bucket");

    private CreateController.InputAsset asset() {
        return new CreateController.InputAsset(UUID.randomUUID().toString(), "uploads/u1/x/image.png",
                "/uploads/x/content", "image/png", "image.png", 100);
    }

    private CreateController.JobRequest request(String prompt, List<String> files,
                                                List<CreateController.InputAsset> assets, String mode) {
        return new CreateController.JobRequest(prompt, files, assets, mode, "init", null);
    }

    @Test
    void promptLongerThan4000IsRejected() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("x".repeat(4001), null, null, "chat"), null));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
        verifyNoInteractions(db);
    }

    @Test
    void legacyFileReferencesAreRejected() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("make a game", List.of("old.txt"), null, "chat"), null));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
    }

    @Test
    void moreThanThreeImagesAreRejected() {
        List<CreateController.InputAsset> assets = List.of(asset(), asset(), asset(), asset());

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("make a game", null, assets, "chat"), null));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
    }

    @Test
    void unknownAgentModeIsRejected() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("make a game", null, null, "bogus"), null));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
    }

    @Test
    void invalidIdempotencyKeyIsRejected() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("make a game", null, null, "chat"), "bad key!"));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
        verifyNoInteractions(db);
    }

    @Test
    void missingAiConfigurationIsRejected() {
        when(db.queryForMap(contains("ai_configs"), any(Object[].class)))
                .thenThrow(new EmptyResultDataAccessException(1));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.create("u1", request("make a game", null, null, "chat"), null));

        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
    }

    @Test
    void baseUrlMustBePublicHttps() {
        assertThrows(ResponseStatusException.class, () -> CreateService.validateBaseUrl("http://api.example.com"));
        assertThrows(ResponseStatusException.class, () -> CreateService.validateBaseUrl("https://user:pass@api.example.com"));
        assertThrows(ResponseStatusException.class, () -> CreateService.validateBaseUrl("ftp://api.example.com"));
        CreateService.validateBaseUrl("https://api.example.com/v1");
    }

    @Test
    void privateEndpointsAreOnlyAllowedWhenExplicitlyEnabled() {
        try {
            assertThrows(ResponseStatusException.class, () -> CreateService.validateBaseUrl("http://mock-llm:8080"));
            CreateService.privateLlmEndpointsAllowed = true;
            CreateService.validateBaseUrl("http://mock-llm:8080");
            CreateService.validateBaseUrl("http://127.0.0.1:9000");
        } finally {
            CreateService.privateLlmEndpointsAllowed = false;
        }
    }

    @Test
    void apiKeyRoundTripsThroughEncryption() {
        String cipher = service.encrypt("sk-live-test-key");

        assertNotEquals("sk-live-test-key", cipher);
        assertEquals("sk-live-test-key", service.decrypt(cipher));
    }
}
