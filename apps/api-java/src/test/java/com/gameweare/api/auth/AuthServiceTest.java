package com.gameweare.api.auth;

import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.sql.ResultSet;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
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
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.ArgumentMatchers.startsWith;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Register/login/logout/session behavior with MySQL as the system of record. */
class AuthServiceTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    @SuppressWarnings("unchecked")
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> values = mock(ValueOperations.class);
    private final AuthService service = new AuthService(jdbc, redis, 5000);

    @Test
    void registerCreatesUserAccountGrantAndSession() {
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);

        AuthService.AuthResponse out = service.register("  User@Example.COM ", "password123", null);

        assertTrue(out.authenticated());
        assertEquals("user@example.com", out.user().email());
        assertEquals("user", out.user().displayName());
        assertEquals("user", out.user().role());
        assertEquals(43, out.accessToken().length());
        verify(jdbc).update(contains("INSERT INTO users"), any(), eq("user@example.com"), any(), eq("user"), eq("user"));
        verify(jdbc).update(contains("INSERT INTO token_accounts"), any(), eq(5000L));
        verify(jdbc).update(contains("token_ledger"), any(), any(), any(), eq("GRANT"), eq(5000L));
        verify(jdbc).update(contains("INSERT INTO user_sessions"), any(), eq(out.user().id()),
                eq(AuthService.hash(out.accessToken())), any(Timestamp.class));
    }

    @Test
    void registerValidatesPasswordAndEmail() {
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.register("user@example.com", "short", null)));
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.register("not-an-email", "password123", null)));
        verifyNoInteractions(jdbc);
    }

    @Test
    void registerRejectsDuplicateEmail() {
        when(jdbc.update(contains("INSERT INTO users"), any(Object[].class)))
                .thenThrow(new DataIntegrityViolationException("duplicate"));

        assertEquals(HttpStatus.CONFLICT, status(() -> service.register("user@example.com", "password123", null)));
    }

    @Test
    void loginIssuesSessionForValidCredentials() throws Exception {
        String bcrypt = new BCryptPasswordEncoder().encode("password123");
        ResultSet rs = mock(ResultSet.class);
        when(rs.getString("id")).thenReturn("u1");
        when(rs.getString("email")).thenReturn("user@example.com");
        when(rs.getString("password_hash")).thenReturn(bcrypt);
        when(rs.getString("display_name")).thenReturn("User");
        when(rs.getString("role")).thenReturn("user");
        when(jdbc.query(contains("FROM users"), any(RowMapper.class), eq("user@example.com")))
                .thenAnswer(invocation -> List.of(((RowMapper<Object>) invocation.getArgument(1)).mapRow(rs, 0)));
        when(jdbc.update(anyString(), any(Object[].class))).thenReturn(1);
        when(redis.execute(any(RedisScript.class), anyList())).thenReturn(1L);

        AuthService.AuthResponse out = service.login("user@example.com", "password123");

        assertTrue(out.authenticated());
        assertEquals("u1", out.user().id());
        verify(jdbc).update("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", "u1");
        verify(jdbc).update(contains("INSERT INTO user_sessions"), any(), eq("u1"),
                eq(AuthService.hash(out.accessToken())), any(Timestamp.class));
    }

    @Test
    void loginRejectsWrongPassword() throws Exception {
        when(jdbc.query(contains("FROM users"), any(RowMapper.class), eq("user@example.com"))).thenReturn(List.of());
        when(redis.execute(any(RedisScript.class), anyList())).thenReturn(1L);

        assertEquals(HttpStatus.UNAUTHORIZED, status(() -> service.login("user@example.com", "wrong-pass")));
    }

    @Test
    void loginIsRateLimited() {
        when(redis.execute(any(RedisScript.class), anyList())).thenReturn(11L);

        assertEquals(HttpStatus.TOO_MANY_REQUESTS, status(() -> service.login("user@example.com", "password123")));
        verifyNoInteractions(jdbc);
    }

    @Test
    void logoutRevokesSessionEverywhere() {
        when(redis.opsForValue()).thenReturn(values);
        String token = new SecureRandomToken().next();

        service.logout(token);

        String hash = AuthService.hash(token);
        verify(values).set(startsWith("auth:revoked:"), eq("1"), any(Duration.class));
        verify(redis).delete("auth:session:" + hash);
        verify(jdbc).update(contains("user_sessions"), eq(hash));
    }

    @Test
    void revokedTokenIsRejectedBeforeCacheOrDatabase() {
        String hash = AuthService.hash("token");
        when(redis.hasKey("auth:revoked:" + hash)).thenReturn(true);

        assertNull(service.findUserByToken("token"));
        verifyNoInteractions(jdbc);
    }

    @Test
    void cachedSessionIsUsedWithoutDatabase() {
        String hash = AuthService.hash("token");
        when(redis.hasKey("auth:revoked:" + hash)).thenReturn(false);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get("auth:session:" + hash)).thenReturn(String.join(":",
                encode("u1"), encode("user@example.com"), encode("User"), encode(""), encode("user"), "1700000000000"));

        AuthService.UserProfile out = service.findUserByToken("token");

        assertNotNull(out);
        assertEquals("u1", out.id());
        assertEquals("user@example.com", out.email());
        verifyNoInteractions(jdbc);
    }

    @Test
    void databaseSessionIsCachedAfterCacheMiss() throws Exception {
        String hash = AuthService.hash("token");
        when(redis.hasKey("auth:revoked:" + hash)).thenReturn(false);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get("auth:session:" + hash)).thenReturn(null);
        ResultSet rs = mock(ResultSet.class);
        when(rs.getString("id")).thenReturn("u1");
        when(rs.getString("email")).thenReturn("user@example.com");
        when(rs.getString("display_name")).thenReturn("User");
        when(rs.getString("avatar_url")).thenReturn(null);
        when(rs.getString("role")).thenReturn("user");
        when(rs.getTimestamp("last_login_at")).thenReturn(Timestamp.from(Instant.now()));
        when(rs.getTimestamp("expires_at")).thenReturn(Timestamp.from(Instant.now().plus(Duration.ofHours(1))));
        when(jdbc.query(contains("user_sessions"), any(RowMapper.class), any(Object[].class)))
                .thenAnswer(invocation -> List.of(((RowMapper<Object>) invocation.getArgument(1)).mapRow(rs, 0)));

        AuthService.UserProfile out = service.findUserByToken("token");

        assertNotNull(out);
        assertEquals("u1", out.id());
        verify(values).set(eq("auth:session:" + hash), anyString(), any(Duration.class));
    }

    @Test
    void expiredOrMissingSessionReturnsNull() {
        when(redis.hasKey(anyString())).thenReturn(false);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenReturn(null);
        when(jdbc.query(anyString(), any(RowMapper.class), any(Object[].class))).thenReturn(List.of());

        assertNull(service.findUserByToken("token"));
    }

    private static String encode(String value) {
        return value == null ? "" : Base64.getUrlEncoder().withoutPadding()
                .encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private org.springframework.http.HttpStatusCode status(Runnable call) {
        return assertThrows(ResponseStatusException.class, call::run).getStatusCode();
    }

    private static final class SecureRandomToken {
        private final SecureRandom random = new SecureRandom();

        String next() {
            byte[] secret = new byte[32];
            random.nextBytes(secret);
            return Base64.getUrlEncoder().withoutPadding().encodeToString(secret);
        }
    }
}
