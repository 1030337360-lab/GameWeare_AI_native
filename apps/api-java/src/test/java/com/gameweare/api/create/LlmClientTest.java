package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class LlmClientTest {
    @Test
    void textOnlyReplyCanBeCorrectedOnNextToolCall() throws Exception {
        ObjectMapper json = new ObjectMapper();
        AtomicInteger calls = new AtomicInteger();
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script>const game = true;</script></body></html>";
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            int number = calls.incrementAndGet();
            String request = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (number == 2 && !request.contains("previous response was text"))
                throw new AssertionError("Missing corrective prompt after text-only response");
            Object item = number == 1
                    ? Map.of("type", "message", "role", "assistant", "content",
                            List.of(Map.of("type", "output_text", "text", "I am working on the game.")))
                    : Map.of("type", "function_call", "name", "validate_game_html", "call_id", "call-2",
                            "arguments", json.writeValueAsString(Map.of("html", html)));
            byte[] response = json.writeValueAsBytes(Map.of("output", List.of(item),
                    "usage", Map.of("input_tokens", 2, "output_tokens", 1, "total_tokens", 3)));
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            LlmClient.Result result = LlmClient.generateValidatedGame(base, "mock", "test", "Make a game",
                    List.of(), new GameValidationTool("job-1", new ArtifactValidator()), ignored -> {});
            assertEquals(html, result.text());
            assertEquals(2, calls.get());
            assertEquals(6, result.totalTokens());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void completeHtmlInTextOnlyReplyStillPassesServerValidation() throws Exception {
        ObjectMapper json = new ObjectMapper();
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script>const game = true;</script></body></html>";
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            exchange.getRequestBody().readAllBytes();
            byte[] response = json.writeValueAsBytes(Map.of("output", List.of(Map.of("type", "message",
                    "content", List.of(Map.of("type", "output_text", "text", "```html\n" + html + "\n```")))),
                    "usage", Map.of("input_tokens", 2, "output_tokens", 1, "total_tokens", 3)));
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            LlmClient.Result result = LlmClient.generateValidatedGame(base, "mock", "test", "Make a game",
                    List.of(), new GameValidationTool("job-1", new ArtifactValidator()), ignored -> {});
            assertEquals(html, result.text());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void validationToolReturnsDiagnosticsAndAcceptsCorrectedHtml() throws Exception {
        ObjectMapper json = new ObjectMapper();
        AtomicInteger calls = new AtomicInteger();
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script>const game = true;</script></body></html>";
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            int number = calls.incrementAndGet();
            String request = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            if (number == 1 && !request.contains("validate_game_html")) throw new AssertionError("tool missing");
            if (number == 2 && (!request.contains("EXTERNAL_HTTP_RESOURCE")
                    || !request.contains("function_call_output")
                    || !request.contains("reasoning")
                    || request.contains("previous_response_id") || request.contains("\"store\"")))
                throw new AssertionError("stateless tool feedback or reasoning replay missing");
            String candidate = number == 1 ? html.replace("const game = true;",
                    "const game = true; fetch('https://invalid.example/game');") : html;
            String event = "data: {\"type\":\"response.completed\",\"response\":"
                    + json.writeValueAsString(Map.of("id", "resp-" + number,
                    "output", List.of(Map.of("type", "reasoning", "content", "keep prior reasoning"),
                            Map.of("type", "function_call", "name", "validate_game_html",
                            "call_id", "call-" + number,
                            "arguments", json.writeValueAsString(Map.of("html", candidate)))),
                    "usage", Map.of("input_tokens", 2, "output_tokens", 1, "total_tokens", 3)))
                    + "}\n\n";
            byte[] response = event.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            List<GameValidationTool.CandidateResult> validations = new ArrayList<>();
            LlmClient.Result result = LlmClient.generateValidatedGame(base, "mock", "test", "Make a game",
                    List.of(), new GameValidationTool("job-1", new ArtifactValidator()), validations::add);
            assertEquals(html, result.text());
            assertEquals(6, result.totalTokens());
            assertEquals(2, calls.get());
            assertEquals(2, validations.size());
            assertTrue(validations.get(0).feedback().contains("EXTERNAL_HTTP_RESOURCE"));
            assertTrue(validations.get(1).passed());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void providerHttpErrorIncludesItsCodeAndMessage() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            byte[] response = "{\"error\":{\"code\":\"quota_exceeded\",\"message\":\"Provider quota exhausted\"}}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(429, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            IllegalStateException failure = assertThrows(IllegalStateException.class,
                    () -> LlmClient.generate(base, "mock", "test", "hello"));
            assertTrue(failure.getMessage().contains("HTTP 429"));
            assertTrue(failure.getMessage().contains("quota_exceeded"));
            assertTrue(failure.getMessage().contains("Provider quota exhausted"));
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void localMockWorksOnlyWithDevelopmentOverride() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            byte[] response = "{\"output_text\":\"ok\",\"usage\":{\"input_tokens\":2,\"output_tokens\":1,\"total_tokens\":3}}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = false;
            assertThrows(IllegalArgumentException.class, () -> LlmClient.generate(base, "mock", "test", "hello"));
            CreateService.privateLlmEndpointsAllowed = true;
            LlmClient.Result result = LlmClient.generate(base, "mock", "test", "hello");
            assertEquals("ok", result.text());
            assertEquals(3, result.totalTokens());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void streamsResponsesAndRequiresACompletedEventWithUsage() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            String request = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            String events = request.contains("\"stream\":true")
                    ? "data: {\"type\":\"response.output_text.delta\",\"delta\":\"ok\"}\n\n"
                        + "data: {\"type\":\"response.completed\",\"response\":{\"output\":[{\"content\":[{\"text\":\"ok\"}]}],\"usage\":{\"input_tokens\":2,\"output_tokens\":1,\"total_tokens\":3}}}\n\n"
                    : "data: {\"type\":\"error\",\"message\":\"stream option missing\"}\n\n";
            byte[] response = events.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream; charset=utf-8");
            exchange.sendResponseHeaders(200, response.length);
            try (var out = exchange.getResponseBody()) { out.write(response); }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            LlmClient.Result result = LlmClient.generate(base, "mock", "test", "hello");
            assertEquals("ok", result.text());
            assertEquals(3, result.totalTokens());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }

    @Test
    void longFunctionArgumentStreamMayExceedEightMegabytesOfTransportFrames() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/responses", exchange -> {
            exchange.getRequestBody().readAllBytes();
            exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, 0);
            try (var out = exchange.getResponseBody()) {
                byte[] delta = ("data: {\"type\":\"response.function_call_arguments.delta\",\"delta\":\""
                        + "x".repeat(100_000) + "\"}\n\n").getBytes(StandardCharsets.UTF_8);
                for (int i = 0; i < 90; i++) out.write(delta);
                out.write(("data: {\"type\":\"response.completed\",\"response\":{"
                        + "\"output_text\":\"ok\",\"usage\":{\"input_tokens\":2,"
                        + "\"output_tokens\":1,\"total_tokens\":3}}}\n\n")
                        .getBytes(StandardCharsets.UTF_8));
            }
        });
        server.start();
        String oldHosts = LlmClient.allowedHosts;
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        try {
            LlmClient.allowedHosts = "127.0.0.1";
            CreateService.privateLlmEndpointsAllowed = true;
            String base = "http://127.0.0.1:" + server.getAddress().getPort() + "/v1";
            assertEquals("ok", LlmClient.generate(base, "mock", "test", "hello").text());
        } finally {
            LlmClient.allowedHosts = oldHosts;
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            server.stop(0);
        }
    }
}
