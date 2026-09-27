package com.gameweare.api.config;

import java.net.URI;
import java.util.Map;

import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

/** Fails production startup before the API accepts requests if deployment secrets are missing. */
@Configuration
@Profile("prod")
public class ProductionConfigGuard {
    public ProductionConfigGuard() {
        validate(System.getenv());
    }

    static void validate(Map<String, String> env) {
        requireSecret(env, "MYSQL_PASSWORD", 16);
        requireSecret(env, "RABBITMQ_PASSWORD", 16);
        requireSecret(env, "REDIS_PASSWORD", 16);
        requireSecret(env, "MINIO_ACCESS_KEY", 8);
        requireSecret(env, "MINIO_SECRET_KEY", 16);
        requireSecret(env, "AI_CONFIG_SECRET", 32);
        if (!"false".equalsIgnoreCase(env.getOrDefault("LLM_ALLOW_PRIVATE_ENDPOINTS", "false").strip()))
            throw new IllegalStateException("LLM_ALLOW_PRIVATE_ENDPOINTS must be false in production");
        String engine = env.getOrDefault("AGENT_ENGINE", "legacy").strip();
        if (!"legacy".equals(engine) && !"agentscope".equals(engine))
            throw new IllegalStateException("AGENT_ENGINE must be legacy or agentscope");
        if (!"kubernetes".equalsIgnoreCase(env.getOrDefault("AGENT_FILESYSTEM", "kubernetes").strip()))
            throw new IllegalStateException("AGENT_FILESYSTEM must be kubernetes in production");
        String hosts = required(env, "LLM_ALLOWED_HOSTS");
        for (String host : hosts.split(",", -1)) {
            String value = host.strip();
            if (!value.matches("(?i)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+")
                    || value.matches("[0-9.]+"))
                throw new IllegalStateException("LLM_ALLOWED_HOSTS must list exact public DNS names");
        }
        requireHttps(env, "WEB_ORIGIN");
        requireHttps(env, "MINIO_PUBLIC_BASE_URL");
    }

    private static void requireSecret(Map<String, String> env, String name, int minimumLength) {
        String value = required(env, name);
        if (value.length() < minimumLength || value.equals("gameweare") || value.equals("minioadmin")
                || value.startsWith("local-") || value.startsWith("replace-"))
            throw new IllegalStateException(name + " is too short or uses a development value");
    }

    private static String required(Map<String, String> env, String name) {
        String value = env.get(name);
        if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required in production");
        return value;
    }

    private static void requireHttps(Map<String, String> env, String name) {
        try {
            URI uri = URI.create(required(env, name));
            if ("https".equalsIgnoreCase(uri.getScheme()) && uri.getHost() != null && uri.getUserInfo() == null)
                return;
        } catch (IllegalArgumentException ignored) { }
        throw new IllegalStateException(name + " must be an HTTPS URL");
    }
}
