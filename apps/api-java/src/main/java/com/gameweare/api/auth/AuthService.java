package com.gameweare.api.auth;

import com.gameweare.api.auth.dao.AuthMapper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AuthService {
    private static final Pattern EMAIL = Pattern.compile("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$");
    private static final long SESSION_SECONDS = Duration.ofDays(7).toSeconds();
    private static final long ABSOLUTE_SESSION_SECONDS = Duration.ofDays(30).toSeconds();
    private static final String DUMMY_HASH = new BCryptPasswordEncoder().encode("not-a-real-password");

    private final AuthMapper authMapper;
    private final StringRedisTemplate redis;
    private final long starterTokens;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder();
    private final SecureRandom random = new SecureRandom();

    public AuthService(AuthMapper authMapper, StringRedisTemplate redis,
                       @Value("${gameweare.billing.starter-tokens:100000}") long starterTokens) {
        this.authMapper = authMapper;
        this.redis = redis;
        this.starterTokens = starterTokens;
        if (starterTokens < 0) throw new IllegalArgumentException("Starter tokens cannot be negative");
    }

    @Transactional
    public AuthResponse register(String rawEmail, String password, String rawDisplayName) {
        String email = normalizeEmail(rawEmail);
        if (password == null || password.length() < 8 || password.getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Password must be at least 8 characters and at most 72 bytes");
        }
        String displayName = rawDisplayName == null || rawDisplayName.isBlank()
                ? email.substring(0, email.indexOf('@')) : rawDisplayName.trim();
        if (displayName.length() > 100) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Display name is too long");
        }
        String userId = UUID.randomUUID().toString();
        try {
            authMapper.insertUser(userId, email, passwords.encode(password), displayName);
        } catch (DataIntegrityViolationException duplicate) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Email already registered", duplicate);
        }
        authMapper.insertAccount(userId, starterTokens);
        if (starterTokens > 0) authMapper.insertStarterGrant(UUID.randomUUID().toString(), userId, userId, starterTokens);
        return issue(new UserProfile(userId, email, displayName, null, "user", Instant.now()));
    }

    @Transactional
    public AuthResponse login(String rawEmail, String password) {
        String email = normalizeEmail(rawEmail);
        checkLoginRate(email);
        if (password != null && password.getBytes(StandardCharsets.UTF_8).length > 72)
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        Map<String, Object> found = authMapper.findLoginUser(email);
        LoginRow row = found == null ? null : new LoginRow(string(found, "id"), string(found, "email"),
                string(found, "password_hash"), string(found, "display_name"), string(found, "role"));
        if (!passwords.matches(password == null ? "" : password, row == null ? DUMMY_HASH : row.passwordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        }
        authMapper.touchLogin(row.id());
        redis.delete("auth:login:attempts:" + hash(email));
        return issue(new UserProfile(row.id(), row.email(), row.displayName(), null, row.role(), Instant.now()));
    }

    @Transactional
    public void logout(String token) {
        if (token != null && !token.isBlank()) {
            String tokenHash = hash(token);
            redis.opsForValue().set("auth:revoked:" + tokenHash, "1", Duration.ofSeconds(ABSOLUTE_SESSION_SECONDS));
            redis.delete("auth:session:" + tokenHash);
            authMapper.revokeSession(tokenHash);
        }
    }

    public UserProfile findUserByToken(String token) {
        if (token == null || token.isBlank() || token.length() > 2048) return null;
        String tokenHash = hash(token);
        if (Boolean.TRUE.equals(redis.hasKey("auth:revoked:" + tokenHash))) return null;
        String cached = redis.opsForValue().get("auth:session:" + tokenHash);
        if (cached != null) {
            try {
                String[] fields = cached.split(":", -1);
                if (fields.length == 8) {
                    UserProfile profile = new UserProfile(decode(fields[0]), decode(fields[1]),
                            decode(fields[2]), decode(fields[3]), decode(fields[4]),
                            fields[5].isEmpty() ? null : Instant.ofEpochMilli(Long.parseLong(fields[5])));
                    Instant expiry = Instant.ofEpochMilli(Long.parseLong(fields[6]));
                    if (expiry.isAfter(Instant.now().plus(Duration.ofDays(1)))) return profile;
                    redis.delete("auth:session:" + tokenHash);
                }
            } catch (RuntimeException corrupt) {
                redis.delete("auth:session:" + tokenHash);
            }
        }
        Map<String, Object> found = authMapper.findActiveSession(tokenHash);
        if (found == null) return null;
        SessionUser session = new SessionUser(user(found), timestamp(found, "expires_at").toInstant(),
                timestamp(found, "created_at").toInstant());
        UserProfile profile = session.profile();
        Instant expiresAt = session.expiresAt();
        if (expiresAt.isBefore(Instant.now().plus(Duration.ofDays(1)))) {
            Instant newExpiry = Instant.now().plusSeconds(SESSION_SECONDS);
            Instant absolute = session.createdAt().plusSeconds(ABSOLUTE_SESSION_SECONDS);
            if (newExpiry.isAfter(absolute)) newExpiry = absolute;
            if (newExpiry.isAfter(expiresAt)) {
                int updated = authMapper.extendSession(java.sql.Timestamp.from(newExpiry), tokenHash);
                if (updated > 0) expiresAt = newExpiry;
            }
        }
        if (Boolean.TRUE.equals(redis.hasKey("auth:revoked:" + tokenHash))) return null;
        String value = String.join(":", encode(profile.id()), encode(profile.email()), encode(profile.displayName()),
                encode(profile.avatarUrl()), encode(profile.role()),
                profile.lastLoginAt() == null ? "" : Long.toString(profile.lastLoginAt().toEpochMilli()),
                Long.toString(expiresAt.toEpochMilli()), Long.toString(session.createdAt().toEpochMilli()));
        long cacheSeconds = Math.min(60, Duration.between(Instant.now(), expiresAt).toSeconds());
        if (cacheSeconds > 0) redis.opsForValue().set("auth:session:" + tokenHash, value, Duration.ofSeconds(cacheSeconds));
        return profile;
    }

    private static String encode(String value) {
        return value == null ? "" : Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static String decode(String value) {
        return value.isEmpty() ? null : new String(Base64.getUrlDecoder().decode(value), StandardCharsets.UTF_8);
    }

    AuthResponse issue(UserProfile user) {
        byte[] secret = new byte[32];
        random.nextBytes(secret);
        String token = Base64.getUrlEncoder().withoutPadding().encodeToString(secret);
        authMapper.insertSession(UUID.randomUUID().toString(), user.id(), hash(token),
                java.sql.Timestamp.from(Instant.now().plusSeconds(SESSION_SECONDS)));
        return new AuthResponse(true, user, token, "bearer", SESSION_SECONDS);
    }

    private static String normalizeEmail(String raw) {
        String email = raw == null ? "" : raw.strip().toLowerCase(Locale.ROOT);
        if (email.length() > 254 || !EMAIL.matcher(email).matches()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid email");
        }
        return email;
    }

    private void checkLoginRate(String email) {
        String key = "auth:login:attempts:" + hash(email);
        var script = new DefaultRedisScript<Long>();
        script.setResultType(Long.class);
        script.setScriptText("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n");
        Long attempts = redis.execute(script, java.util.List.of(key));
        if (attempts == null || attempts > 10)
            throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS, "Too many login attempts");
    }

    static String hash(String token) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    static UserProfile user(ResultSet rs) throws SQLException {
        var lastLogin = rs.getTimestamp("last_login_at");
        return new UserProfile(rs.getString("id"), rs.getString("email"), rs.getString("display_name"),
                rs.getString("avatar_url"), rs.getString("role"), lastLogin == null ? null : lastLogin.toInstant());
    }

    static UserProfile user(Map<String, Object> row) {
        java.sql.Timestamp lastLogin = timestamp(row, "last_login_at");
        return new UserProfile(string(row, "id"), string(row, "email"), string(row, "display_name"),
                string(row, "avatar_url"), string(row, "role"), lastLogin == null ? null : lastLogin.toInstant());
    }

    private static String string(Map<String, Object> row, String column) {
        Object value = row.get(column);
        return value == null ? null : value.toString();
    }

    private static java.sql.Timestamp timestamp(Map<String, Object> row, String column) {
        Object value = row.get(column);
        if (value == null) return null;
        if (value instanceof java.sql.Timestamp timestamp) return timestamp;
        // MyBatis' default Map result uses LocalDateTime for MySQL DATETIME/TIMESTAMP.
        if (value instanceof java.time.LocalDateTime dateTime) {
            return java.sql.Timestamp.from(dateTime.toInstant(java.time.ZoneOffset.UTC));
        }
        throw new IllegalStateException("Unexpected SQL timestamp type for " + column + ": " + value.getClass());
    }

    private record LoginRow(String id, String email, String passwordHash, String displayName, String role) {}
    private record SessionUser(UserProfile profile, Instant expiresAt, Instant createdAt) {}

    public record UserProfile(String id, String email, String displayName, String avatarUrl, String role,
                              Instant lastLoginAt) {}
    public record AuthResponse(boolean authenticated, UserProfile user, String accessToken, String tokenType,
                               long expiresIn) {}
    public record SessionState(boolean authenticated, UserProfile user) {}
}
