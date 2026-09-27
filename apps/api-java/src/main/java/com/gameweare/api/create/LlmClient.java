package com.gameweare.api.create;

import java.net.Proxy;
import java.net.URI;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

final class LlmClient {
    private static final ObjectMapper JSON = new ObjectMapper();
    static volatile String allowedHosts = "";

    record Result(String text, long promptTokens, long completionTokens, long totalTokens) {}
    record Image(String dataUrl) {}

    static Result generate(String baseUrl, String model, String apiKey, String prompt) throws Exception {
        return generate(baseUrl, model, apiKey, prompt, List.of());
    }

    static Result generate(String baseUrl, String model, String apiKey, String prompt, List<Image> images) throws Exception {
        LlmEndpointPolicy policy = new LlmEndpointPolicy(allowedHosts, CreateService.privateLlmEndpointsAllowed);
        URI base = URI.create(baseUrl.strip());
        policy.validate(base);
        String endpoint = base.toString().replaceAll("/+$", "");
        if (!endpoint.endsWith("/responses")) endpoint += "/responses";
        URI uri = URI.create(endpoint);
        policy.validate(uri);
        Object input;
        if (images.isEmpty()) input = prompt;
        else {
            List<Map<String, String>> content = new ArrayList<>();
            content.add(Map.of("type", "input_text", "text", prompt));
            for (Image image : images) content.add(Map.of("type", "input_image", "image_url", image.dataUrl()));
            input = List.of(Map.of("role", "user", "content", content));
        }
        String body = JSON.writeValueAsString(Map.of("model", model, "input", input));
        OkHttpClient http = new OkHttpClient.Builder()
                .proxy(Proxy.NO_PROXY).followRedirects(false).followSslRedirects(false)
                .dns(policy::resolve).connectTimeout(Duration.ofSeconds(10))
                .readTimeout(Duration.ofSeconds(180))
                .callTimeout(Duration.ofSeconds(240)).build();
        Request request = new Request.Builder().url(uri.toString())
                .header("Authorization", "Bearer " + apiKey)
                .post(RequestBody.create(body, MediaType.get("application/json"))).build();
        try (Response response = http.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                String details = "";
                if (response.body() != null) {
                    byte[] errorBytes = response.body().byteStream().readNBytes(4_001);
                    try {
                        JsonNode providerError = JSON.readTree(errorBytes).path("error");
                        String code = providerError.path("code").asText("");
                        String type = providerError.path("type").asText("");
                        String message = providerError.path("message").asText("");
                        if (!code.isBlank()) details += " code=" + code;
                        if (!type.isBlank()) details += " type=" + type;
                        if (!message.isBlank()) details += " message=" + message;
                    } catch (Exception ignored) {
                        details = " (provider error body was not valid JSON)";
                    }
                }
                throw new IllegalStateException("AI provider returned HTTP " + response.code() + details);
            }
            if (response.body() == null) throw new IllegalStateException("AI provider returned an empty response");
            byte[] responseBytes = response.body().byteStream().readNBytes(4_000_001);
            if (responseBytes.length > 4_000_000)
                throw new IllegalStateException("AI provider response is too large");
            String responseJson = new String(responseBytes, java.nio.charset.StandardCharsets.UTF_8);
            JsonNode root = JSON.readTree(responseJson);
            String text = root.path("output_text").asText("");
            if (text.isBlank()) {
                StringBuilder result = new StringBuilder();
                for (JsonNode item : root.path("output"))
                    for (JsonNode part : item.path("content")) {
                        String fragment = part.path("text").asText("");
                        if (!fragment.isBlank()) result.append(fragment);
                    }
                text = result.toString();
            }
            if (text.isBlank()) throw new IllegalStateException("AI provider returned no text");
            long promptTokens = root.path("usage").path("input_tokens").asLong(-1);
            long completionTokens = root.path("usage").path("output_tokens").asLong(-1);
            long tokens = root.path("usage").path("total_tokens").asLong(-1);
            if (tokens < 0 || promptTokens < 0 || completionTokens < 0 || promptTokens + completionTokens != tokens)
                throw new IllegalStateException("AI provider did not return consistent token usage");
            return new Result(text, promptTokens, completionTokens, tokens);
        }
    }
}
