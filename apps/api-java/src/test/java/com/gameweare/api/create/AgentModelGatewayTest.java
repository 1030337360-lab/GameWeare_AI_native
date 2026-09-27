package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

class AgentModelGatewayTest {
    @Test
    void loopbackTokenGatewayForwardsWithRealKeyAndClosesRegistration() throws Exception {
        HttpServer provider = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> authorization = new AtomicReference<>();
        provider.createContext("/v1/chat/completions", exchange -> {
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            byte[] reply = "{\"choices\":[]}".getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, reply.length);
            exchange.getResponseBody().write(reply);
            exchange.close();
        });
        provider.start();
        boolean oldPrivate = CreateService.privateLlmEndpointsAllowed;
        String oldHosts = LlmClient.allowedHosts;
        try {
            CreateService.privateLlmEndpointsAllowed = true;
            LlmClient.allowedHosts = "";
            AgentModelGateway gateway = new AgentModelGateway(8080);
            MockHttpServletRequest request = new MockHttpServletRequest("POST", "/internal/agent-model");
            request.setRemoteAddr("127.0.0.1");
            request.setContent("{}".getBytes(StandardCharsets.UTF_8));
            String token;
            try (var registration = gateway.register(
                    "http://127.0.0.1:" + provider.getAddress().getPort() + "/v1", "real-key")) {
                token = registration.token();
                var result = gateway.forward(token, "Bearer " + token, request);
                assertEquals(200, result.getStatusCode().value());
                assertEquals("Bearer real-key", authorization.get());
                assertTrue(registration.baseUrl().startsWith("http://127.0.0.1:8080/internal/agent-model/"));
            }
            assertEquals(401, gateway.forward(token, "Bearer " + token, request)
                    .getStatusCode().value());
            request.setRemoteAddr("203.0.113.1");
            assertEquals(403, gateway.forward(token, "Bearer " + token, request)
                    .getStatusCode().value());
        } finally {
            CreateService.privateLlmEndpointsAllowed = oldPrivate;
            LlmClient.allowedHosts = oldHosts;
            provider.stop(0);
        }
    }
}
