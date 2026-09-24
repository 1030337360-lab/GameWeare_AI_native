package com.gameweare.api.create;

import java.net.InetAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

final class LlmClient {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    record Result(String text, long promptTokens, long completionTokens, long totalTokens) {}
    record Image(String dataUrl) {}

    static Result generate(String baseUrl, String model, String apiKey, String prompt) throws Exception {
        return generate(baseUrl, model, apiKey, prompt, List.of());
    }

    static Result generate(String baseUrl, String model, String apiKey, String prompt, List<Image> images) throws Exception {
        CreateService.validateBaseUrl(baseUrl);
        String endpoint = baseUrl.strip().replaceAll("/+$", "");
        if (!endpoint.endsWith("/responses")) endpoint += "/responses";
        URI uri = URI.create(endpoint);
        if (!CreateService.privateLlmEndpointsAllowed)
            for (InetAddress address : InetAddress.getAllByName(uri.getHost())) {
                if (!isPublicAddress(address))
                    throw new IllegalArgumentException("AI provider address is not public");
            }
        Object input;
        if (images.isEmpty()) input = prompt;
        else {
            List<Map<String, String>> content = new ArrayList<>();
            content.add(Map.of("type", "input_text", "text", prompt));
            for (Image image : images) content.add(Map.of("type", "input_image", "image_url", image.dataUrl()));
            input = List.of(Map.of("role", "user", "content", content));
        }
        String body = JSON.writeValueAsString(Map.of("model", model, "input", input, "max_output_tokens", 3072));
        HttpRequest request = HttpRequest.newBuilder(URI.create(endpoint))
                .timeout(Duration.ofSeconds(120))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + apiKey)
                .POST(HttpRequest.BodyPublishers.ofString(body)).build();
        HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300)
            throw new IllegalStateException("AI provider returned HTTP " + response.statusCode());
        JsonNode root = JSON.readTree(response.body());
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

    private static boolean isPublicAddress(InetAddress address) {
        if (address.isAnyLocalAddress() || address.isLoopbackAddress() || address.isLinkLocalAddress()
                || address.isSiteLocalAddress() || address.isMulticastAddress()) return false;
        byte[] bytes = address.getAddress();
        if (bytes.length == 4) {
            int first = bytes[0] & 255;
            int second = bytes[1] & 255;
            if (first == 0 || first >= 224 || first == 100 && second >= 64 && second <= 127
                    || first == 192 && second == 0 || first == 198 && (second == 18 || second == 19)) return false;
        } else if (bytes.length == 16 && ((bytes[0] & 0xfe) == 0xfc || (bytes[0] & 255) == 0x20 && (bytes[1] & 255) == 0x01)) {
            return false;
        }
        return true;
    }
}
