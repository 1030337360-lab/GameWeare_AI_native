package com.gameweare.api.auth;

import com.gameweare.api.auth.dao.AuthMapper;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.Base64;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Login and session behavior with mapper SQL and MySQL as the system of record. */
class AuthServiceTest {
    private final AuthMapper mapper = mock(AuthMapper.class);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> values = mock(ValueOperations.class);
    private final AuthService service = new AuthService(mapper, redis, 5000);

    @Test void registerCreatesUserAccountGrantAndSession() {
        var out = service.register("  User@Example.COM ", "password123", null);
        assertTrue(out.authenticated());
        assertEquals("user@example.com", out.user().email());
        assertEquals("user", out.user().displayName());
        assertEquals(43, out.accessToken().length());
        verify(mapper).insertUser(eq(out.user().id()), eq("user@example.com"), anyString(), eq("user"));
        verify(mapper).insertAccount(out.user().id(), 5000);
        verify(mapper).insertStarterGrant(anyString(), eq(out.user().id()), eq(out.user().id()), eq(5000L));
        verify(mapper).insertSession(anyString(), eq(out.user().id()),
                eq(AuthService.hash(out.accessToken())), any(Timestamp.class));
    }

    @Test void registerValidatesPasswordAndEmail() {
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.register("user@example.com", "short", null)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.register("not-an-email", "password123", null)));
        verifyNoInteractions(mapper);
    }

    @Test void registerRejectsDuplicateEmail() {
        when(mapper.insertUser(anyString(), anyString(), anyString(), anyString()))
                .thenThrow(new DataIntegrityViolationException("duplicate"));
        assertEquals(HttpStatus.CONFLICT, status(() -> service.register("user@example.com", "password123", null)));
    }

    @Test void loginIssuesSessionForValidCredentials() {
        String bcrypt = new BCryptPasswordEncoder().encode("password123");
        when(mapper.findLoginUser("user@example.com")).thenReturn(Map.of(
                "id", "u1", "email", "user@example.com", "password_hash", bcrypt,
                "display_name", "User", "role", "user"));
        when(redis.execute(any(RedisScript.class), anyList())).thenReturn(1L);
        var out = service.login("user@example.com", "password123");
        assertEquals("u1", out.user().id());
        verify(mapper).touchLogin("u1");
        verify(mapper).insertSession(anyString(), eq("u1"),
                eq(AuthService.hash(out.accessToken())), any(Timestamp.class));
    }

    @Test void loginRejectsWrongPasswordAndRateLimits() {
        when(redis.execute(any(RedisScript.class), anyList())).thenReturn(1L, 11L);
        assertEquals(HttpStatus.UNAUTHORIZED, status(() -> service.login("user@example.com", "wrong-pass")));
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, status(() -> service.login("user@example.com", "password123")));
    }

    @Test void logoutRevokesSessionEverywhere() {
        when(redis.opsForValue()).thenReturn(values);
        service.logout("token");
        String hash = AuthService.hash("token");
        verify(values).set(eq("auth:revoked:" + hash), eq("1"), any(Duration.class));
        verify(redis).delete("auth:session:" + hash);
        verify(mapper).revokeSession(hash);
    }

    @Test void revokedTokenIsRejectedBeforeDatabase() {
        when(redis.hasKey("auth:revoked:" + AuthService.hash("token"))).thenReturn(true);
        assertNull(service.findUserByToken("token"));
        verifyNoInteractions(mapper);
    }

    @Test void cachedSessionIsUsedWithoutDatabase() {
        String hash = AuthService.hash("token");
        when(redis.opsForValue()).thenReturn(values);
        when(values.get("auth:session:" + hash)).thenReturn(String.join(":",
                encode("u1"), encode("user@example.com"), encode("User"), "", encode("user"), "",
                Long.toString(Instant.now().plus(Duration.ofDays(2)).toEpochMilli()),
                Long.toString(Instant.now().toEpochMilli())));
        assertEquals("u1", service.findUserByToken("token").id());
        verifyNoInteractions(mapper);
    }

    @Test void databaseSessionIsCachedAfterCacheMiss() {
        String hash = AuthService.hash("token");
        when(redis.opsForValue()).thenReturn(values);
        when(mapper.findActiveSession(hash)).thenReturn(Map.of(
                "id", "u1", "email", "user@example.com", "display_name", "User", "role", "user",
                "last_login_at", Timestamp.from(Instant.now()),
                "expires_at", Timestamp.from(Instant.now().plus(Duration.ofHours(1))),
                "created_at", Timestamp.from(Instant.now())));
        var out = service.findUserByToken("token");
        assertNotNull(out);
        assertEquals("u1", out.id());
        verify(values).set(eq("auth:session:" + hash), anyString(), any(Duration.class));
    }

    @Test void myBatisLocalDateTimeUsesUtcForSessionAndProfile() {
        String hash = AuthService.hash("token");
        Instant lastLogin = Instant.parse("2026-09-30T05:00:00Z");
        when(redis.opsForValue()).thenReturn(values);
        when(mapper.findActiveSession(hash)).thenReturn(Map.of(
                "id", "u1", "email", "user@example.com", "display_name", "User", "role", "user",
                "last_login_at", LocalDateTime.ofInstant(lastLogin, ZoneOffset.UTC),
                "expires_at", LocalDateTime.ofInstant(Instant.now().plus(Duration.ofDays(2)), ZoneOffset.UTC),
                "created_at", LocalDateTime.ofInstant(Instant.now(), ZoneOffset.UTC)));
        assertEquals(lastLogin, service.findUserByToken("token").lastLoginAt());
    }

    @Test void expiredOrMissingSessionReturnsNull() {
        when(redis.opsForValue()).thenReturn(values);
        when(mapper.findActiveSession(AuthService.hash("token"))).thenReturn(null);
        assertNull(service.findUserByToken("token"));
    }

    private static String encode(String value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    private org.springframework.http.HttpStatusCode status(Runnable call) {
        return assertThrows(ResponseStatusException.class, call::run).getStatusCode();
    }
}
