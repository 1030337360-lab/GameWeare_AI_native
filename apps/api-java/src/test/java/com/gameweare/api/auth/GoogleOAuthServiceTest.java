package com.gameweare.api.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class GoogleOAuthServiceTest {
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> values = mock(ValueOperations.class);

    private GoogleOAuthService service() {
        when(redis.opsForValue()).thenReturn(values);
        return new GoogleOAuthService("client-id", "client-secret", "https://api.example.test/auth/google/callback",
                "https://web.example.test", 100, redis, mock(JdbcTemplate.class), mock(TransactionTemplate.class),
                mock(AuthService.class), new ObjectMapper());
    }

    @Test void startStoresSingleUseStateAndBuildsGoogleRedirect() {
        when(values.setIfAbsent(startsWith("auth:google:state:"), eq("login"), any(java.time.Duration.class))).thenReturn(true);
        URI url = service().start(null);
        assertEquals("accounts.google.com", url.getHost());
        assertTrue(url.getRawQuery().contains("redirect_uri=https%3A%2F%2Fapi.example.test%2Fauth%2Fgoogle%2Fcallback"));
        String state = java.util.Arrays.stream(url.getRawQuery().split("&"))
                .filter(value -> value.startsWith("state=")).findFirst().orElseThrow().substring(6);
        assertEquals(43, URLDecoder.decode(state, StandardCharsets.UTF_8).length());
        verify(values).setIfAbsent(eq("auth:google:state:" + state), eq("login"), eq(java.time.Duration.ofMinutes(10)));
    }

    @Test void callbackRejectsMissingOrReplayedStateBeforeTokenExchange() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service().callback("authorization-code", "A".repeat(43)));
        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
        verify(values).getAndDelete("auth:google:state:" + "A".repeat(43));
    }

    @Test void missingConfigurationCannotStart() {
        GoogleOAuthService service = new GoogleOAuthService("", "", "https://api.example.test/callback",
                "https://web.example.test", 100, redis, mock(JdbcTemplate.class), mock(TransactionTemplate.class),
                mock(AuthService.class), new ObjectMapper());
        ResponseStatusException error = assertThrows(ResponseStatusException.class, () -> service.start(null));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.getStatusCode());
    }
}
