package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class LlmClientTest {
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
}
