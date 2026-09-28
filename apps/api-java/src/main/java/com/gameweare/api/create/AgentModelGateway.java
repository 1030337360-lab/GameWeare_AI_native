package com.gameweare.api.create;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.servlet.http.HttpServletRequest;
import java.net.InetAddress;
import java.net.Proxy;
import java.net.URI;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** Loopback-only model gateway for AgentScope's OpenAI-compatible chat endpoint. */
@RestController
final class AgentModelGateway {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final int MAX_REQUEST_BYTES = 4 * 1024 * 1024;
    private static final int MAX_RESPONSE_BYTES = 8 * 1024 * 1024;
    private final SecureRandom random = new SecureRandom();
    private final Map<String, Target> targets = new ConcurrentHashMap<>();
    private final int port;

    AgentModelGateway(@Value("${server.port:8080}") int port) { this.port = port; }

    Registration register(String baseUrl, String apiKey) {
        LlmEndpointPolicy policy = new LlmEndpointPolicy(
                LlmClient.allowedHosts, CreateService.privateLlmEndpointsAllowed);
        URI base = URI.create(baseUrl.strip().replaceAll("/+$", "")
                .replaceFirst("/responses$", "").replaceFirst("/chat/completions$", ""));
        policy.validate(base);
        URI endpoint = URI.create(base.toString() + "/chat/completions");
        policy.validate(endpoint);
        byte[] bytes = new byte[32];
        random.nextBytes(bytes);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
        OkHttpClient http = new OkHttpClient.Builder().proxy(Proxy.NO_PROXY)
                .followRedirects(false).followSslRedirects(false)
                .dns(policy::resolve).connectTimeout(Duration.ofSeconds(10))
                // Game HTML is much longer than the one-word configuration probe. OkHttp's
                // default 10-second read timeout incorrectly aborts a healthy generation.
                .readTimeout(Duration.ofSeconds(180))
                .callTimeout(Duration.ofSeconds(240)).build();
        targets.put(token, new Target(endpoint, apiKey, http));
        return new Registration(token, "http://127.0.0.1:" + port + "/internal/agent-model/" + token + "/v1");
    }

    @PostMapping(path = "/internal/agent-model/{token}/v1/chat/completions")
    ResponseEntity<byte[]> forward(@PathVariable String token,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            HttpServletRequest request) throws Exception {
        if (!InetAddress.getByName(request.getRemoteAddr()).isLoopbackAddress())
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        Target target = targets.get(token);
        if (target == null || !("Bearer " + token).equals(authorization))
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        byte[] body = request.getInputStream().readNBytes(MAX_REQUEST_BYTES + 1);
        if (body.length > MAX_REQUEST_BYTES)
            return ResponseEntity.status(HttpStatus.PAYLOAD_TOO_LARGE).build();
        body = compatibleChatRequest(body);
        Request outbound = new Request.Builder().url(target.endpoint().toString())
                .header("Authorization", "Bearer " + target.apiKey())
                .post(RequestBody.create(body, MediaType.get("application/json"))).build();
        try (okhttp3.Response response = target.http().newCall(outbound).execute()) {
            byte[] content = response.body() == null ? new byte[0]
                    : response.body().byteStream().readNBytes(MAX_RESPONSE_BYTES + 1);
            if (content.length > MAX_RESPONSE_BYTES)
                return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
            if (response.isRedirect())
                return ResponseEntity.status(HttpStatus.BAD_GATEWAY).build();
            return ResponseEntity.status(response.code())
                    .contentType(org.springframework.http.MediaType.APPLICATION_JSON).body(content);
        }
    }

    /** Remove optional parameters that the selected DeepSeek model cannot accept. */
    static byte[] compatibleChatRequest(byte[] body) throws Exception {
        JsonNode parsed = JSON.readTree(body);
        if (!(parsed instanceof ObjectNode request)) return body;
        String model = request.path("model").asText("").toLowerCase(Locale.ROOT);
        if (!model.contains("deepseek")) return body;
        boolean changed = request.remove("thinkmode") != null;
        changed |= request.remove("thinking_mode") != null;
        if (model.contains("v4.1-flash") || model.contains("v4-1-flash")) {
            changed |= request.remove("frequency_penalty") != null;
            changed |= request.remove("presence_penalty") != null;
        }
        return changed ? JSON.writeValueAsBytes(request) : body;
    }

    final class Registration implements AutoCloseable {
        private final String token;
        private final String baseUrl;
        private Registration(String token, String baseUrl) { this.token = token; this.baseUrl = baseUrl; }
        String token() { return token; }
        String baseUrl() { return baseUrl; }
        @Override public void close() {
            Target removed = targets.remove(token);
            if (removed != null) {
                removed.http().connectionPool().evictAll();
                removed.http().dispatcher().executorService().shutdown();
            }
        }
    }

    private record Target(URI endpoint, String apiKey, OkHttpClient http) {}
}
