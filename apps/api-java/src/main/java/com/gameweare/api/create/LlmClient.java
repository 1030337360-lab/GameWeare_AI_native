package com.gameweare.api.create;

import java.net.Proxy;
import java.net.URI;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Consumer;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;

final class LlmClient {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final long MAX_STREAM_BYTES = 128L * 1024 * 1024;
    static volatile String allowedHosts = "";

    record Result(String text, long promptTokens, long completionTokens, long totalTokens) {}
    record Image(String dataUrl) {}

    static Result generate(String baseUrl, String model, String apiKey, String prompt) throws Exception {
        return generate(baseUrl, model, apiKey, prompt, List.of());
    }

    static Result generate(String baseUrl, String model, String apiKey, String prompt, List<Image> images) throws Exception {
        JsonNode root = request(baseUrl, apiKey, Map.of("model", model, "input", input(prompt, images), "stream", true));
        return parseResult(root);
    }

    /** The legacy engine uses the same validation tool as the sandbox agent via Responses function calls. */
    static Result generateValidatedGame(String baseUrl, String model, String apiKey, String prompt,
            List<Image> images, GameValidationTool validator,
            Consumer<GameValidationTool.CandidateResult> onValidation) throws Exception {
        Map<String, Object> parameters = Map.of("type", "object",
                "properties", Map.of("html", Map.of("type", "string",
                        "description", "Complete self-contained index.html source to validate")),
                "required", List.of("html"), "additionalProperties", false);
        Map<String, Object> tool = Map.of("type", "function", "name", "validate_game_html",
                "description", "Validate the complete game HTML, inline JavaScript and external resource policy. "
                        + "Call again with corrected HTML after every FAIL. Only a PASS may be delivered.",
                "parameters", parameters);
        Object input = input(prompt, images);
        String previousResponseId = null;
        long promptTokens = 0, completionTokens = 0, totalTokens = 0;
        while (true) {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", model);
            payload.put("input", input);
            payload.put("stream", true);
            payload.put("store", true);
            payload.put("tools", List.of(tool));
            payload.put("tool_choice", Map.of("type", "function", "name", "validate_game_html"));
            payload.put("instructions", "Produce a complete playable single-file HTML game. "
                    + "Submit the complete HTML through validate_game_html. "
                    + "If validation returns FAIL, correct every reported issue and call the tool again. "
                    + "Do not finish with text before the tool reports PASS.");
            if (previousResponseId != null) payload.put("previous_response_id", previousResponseId);
            JsonNode root = request(baseUrl, apiKey, payload);
            long[] usage = usage(root);
            promptTokens = Math.addExact(promptTokens, usage[0]);
            completionTokens = Math.addExact(completionTokens, usage[1]);
            totalTokens = Math.addExact(totalTokens, usage[2]);
            List<Map<String, String>> toolOutputs = new ArrayList<>();
            for (JsonNode item : root.path("output")) {
                if (!"function_call".equals(item.path("type").asText())) continue;
                if (!"validate_game_html".equals(item.path("name").asText()))
                    throw new IllegalStateException("AI provider requested an unknown validation tool");
                String callId = item.path("call_id").asText("");
                if (callId.isBlank()) throw new IllegalStateException("AI provider omitted validation call_id");
                GameValidationTool.CandidateResult result;
                try {
                    JsonNode args = JSON.readTree(item.path("arguments").asText());
                    JsonNode html = args.path("html");
                    if (!html.isTextual()) throw new IllegalArgumentException("html must be a string");
                    result = validator.validateCandidate(html.asText());
                } catch (Exception invalidArguments) {
                    result = new GameValidationTool.CandidateResult(false, "",
                            "FAIL: validate_game_html requires JSON arguments with a complete html string: "
                                    + invalidArguments.getMessage());
                }
                onValidation.accept(result);
                if (result.passed())
                    return new Result(result.normalizedHtml(), promptTokens, completionTokens, totalTokens);
                toolOutputs.add(Map.of("type", "function_call_output", "call_id", callId,
                        "output", result.feedback()));
            }
            if (toolOutputs.isEmpty())
                throw new IllegalStateException("AI provider did not call validate_game_html; game was not delivered");
            previousResponseId = root.path("id").asText("");
            if (previousResponseId.isBlank())
                throw new IllegalStateException("AI provider omitted response id needed to return validation feedback");
            input = toolOutputs;
        }
    }

    private static Object input(String prompt, List<Image> images) {
        if (images.isEmpty()) return prompt;
        List<Map<String, String>> content = new ArrayList<>();
        content.add(Map.of("type", "input_text", "text", prompt));
        for (Image image : images) content.add(Map.of("type", "input_image", "image_url", image.dataUrl()));
        return List.of(Map.of("role", "user", "content", content));
    }

    private static JsonNode request(String baseUrl, String apiKey, Map<String, Object> payload) throws Exception {
        LlmEndpointPolicy policy = new LlmEndpointPolicy(allowedHosts, CreateService.privateLlmEndpointsAllowed);
        URI base = URI.create(baseUrl.strip());
        policy.validate(base);
        String endpoint = base.toString().replaceAll("/+$", "");
        if (!endpoint.endsWith("/responses")) endpoint += "/responses";
        URI uri = URI.create(endpoint);
        policy.validate(uri);
        String body = JSON.writeValueAsString(payload);
        OkHttpClient http = new OkHttpClient.Builder()
                .proxy(Proxy.NO_PROXY).followRedirects(false).followSslRedirects(false)
                .dns(policy::resolve).connectTimeout(Duration.ofSeconds(10))
                .readTimeout(Duration.ofSeconds(180))
                .callTimeout(Duration.ofMinutes(10)).build();
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
            JsonNode root;
            String contentType = response.header("Content-Type", "");
            if (contentType.toLowerCase(java.util.Locale.ROOT).startsWith("text/event-stream")) {
                root = readCompletedStream(response);
            } else {
                byte[] responseBytes = response.body().byteStream().readNBytes(4_000_001);
                if (responseBytes.length > 4_000_000)
                    throw new IllegalStateException("AI provider response is too large");
                root = JSON.readTree(responseBytes);
            }
            return root;
        }
    }

    private static JsonNode readCompletedStream(Response response) throws Exception {
        long receivedBytes = 0;
        StringBuilder eventData = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                response.body().byteStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                receivedBytes += line.getBytes(StandardCharsets.UTF_8).length + 1;
                if (receivedBytes > MAX_STREAM_BYTES)
                    throw new IllegalStateException("AI provider stream exceeded " + MAX_STREAM_BYTES
                            + " bytes after receiving " + receivedBytes + " bytes");
                if (line.isEmpty()) {
                    JsonNode completed = processEvent(eventData);
                    if (completed != null) return completed;
                    eventData.setLength(0);
                } else if (line.startsWith("data:")) {
                    if (!eventData.isEmpty()) eventData.append('\n');
                    eventData.append(line.substring(5).stripLeading());
                }
            }
            JsonNode completed = processEvent(eventData);
            if (completed != null) return completed;
        }
        throw new IllegalStateException("AI provider stream ended before response.completed");
    }

    private static JsonNode processEvent(StringBuilder eventData) throws Exception {
        if (eventData.isEmpty() || "[DONE]".contentEquals(eventData)) return null;
        JsonNode event = JSON.readTree(eventData.toString());
        String type = event.path("type").asText("");
        if ("response.completed".equals(type)) return event.path("response");
        if ("response.failed".equals(type) || "response.incomplete".equals(type) || "error".equals(type)) {
            JsonNode error = event.path("response").path("error");
            if (error.isMissingNode() || error.isNull()) error = event.path("error");
            String message = error.path("message").asText(event.path("message").asText(type));
            throw new IllegalStateException("AI provider stream failed: " + message);
        }
        return null;
    }

    private static Result parseResult(JsonNode root) {
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
            long[] usage = usage(root);
            return new Result(text, usage[0], usage[1], usage[2]);
    }

    private static long[] usage(JsonNode root) {
        long promptTokens = root.path("usage").path("input_tokens").asLong(-1);
        long completionTokens = root.path("usage").path("output_tokens").asLong(-1);
        long tokens = root.path("usage").path("total_tokens").asLong(-1);
        if (tokens < 0 || promptTokens < 0 || completionTokens < 0 || promptTokens + completionTokens != tokens)
            throw new IllegalStateException("AI provider did not return consistent token usage");
        return new long[] {promptTokens, completionTokens, tokens};
    }
}
