package com.gameweare.api.config;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.util.HashMap;
import java.util.Map;

import org.junit.jupiter.api.Test;

class ProductionConfigGuardTest {
    private Map<String, String> valid() {
        return new HashMap<>(Map.of(
                "MYSQL_PASSWORD", "database-secret-123456789",
                "RABBITMQ_PASSWORD", "rabbit-secret-123456789",
                "REDIS_PASSWORD", "redis-secret-123456789",
                "MINIO_ACCESS_KEY", "objectaccess123",
                "MINIO_SECRET_KEY", "object-secret-123456789",
                "AI_CONFIG_SECRET", "production-aes-key-with-more-than-32-chars",
                "LLM_ALLOWED_HOSTS", "api.example.com",
                "WEB_ORIGIN", "https://game.example.com",
                "MINIO_PUBLIC_BASE_URL", "https://objects.example.com/gameweare-games"));
    }

    @Test
    void rejectsMissingSecretsAndUnsafeEgress() {
        assertDoesNotThrow(() -> ProductionConfigGuard.validate(valid()));
        Map<String, String> missingSecretVars = valid();
        missingSecretVars.remove("AI_CONFIG_SECRET");
        assertThrows(IllegalStateException.class, () -> ProductionConfigGuard.validate(missingSecretVars));
        Map<String, String> privateVars = valid();
        privateVars.put("LLM_ALLOW_PRIVATE_ENDPOINTS", "true");
        assertThrows(IllegalStateException.class, () -> ProductionConfigGuard.validate(privateVars));
        Map<String, String> wildcardVars = valid();
        wildcardVars.put("LLM_ALLOWED_HOSTS", "*.example.com");
        assertThrows(IllegalStateException.class, () -> ProductionConfigGuard.validate(wildcardVars));
    }
}
