package com.gameweare.api.auth;

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
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
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
    private static final String DUMMY_HASH = new BCryptPasswordEncoder().encode("not-a-real-password");

    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final long starterTokens;
    private final BCryptPasswordEncoder passwords = new BCryptPasswordEncoder();
    private final SecureRandom random = new SecureRandom();

    public AuthService(JdbcTemplate jdbc, StringRedisTemplate redis,
                       @Value("${gameweare.billing.starter-tokens:100000}") long starterTokens) {
        this.jdbc = jdbc;
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
            jdbc.update("INSERT INTO users(id,email,password_hash,display_name,role,last_login_at,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    userId, email, passwords.encode(password), displayName, "user");
        } catch (DataIntegrityViolationException duplicate) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Email already registered", duplicate);
        }
        jdbc.update("INSERT INTO token_accounts(user_id,balance,reserved,version) VALUES(?,?,0,0)", userId, starterTokens);
        if (starterTokens > 0) jdbc.update(
                "INSERT INTO token_ledger(id,user_id,job_id,entry_type,amount,created_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                UUID.randomUUID().toString(), userId, userId, "GRANT", starterTokens);
        return issue(new UserProfile(userId, email, displayName, null, "user", Instant.now()));
    }

    @Transactional
    public AuthResponse login(String rawEmail, String password) {
        String email = normalizeEmail(rawEmail);
        checkLoginRate(email);
        if (password != null && password.getBytes(StandardCharsets.UTF_8).length > 72)
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        var users = jdbc.query("SELECT id,email,password_hash,display_name,role FROM users WHERE email=?",
                (rs, ignored) -> new LoginRow(rs.getString("id"), rs.getString("email"),
                        rs.getString("password_hash"), rs.getString("display_name"), rs.getString("role")), email);
        LoginRow row = users.isEmpty() ? null : users.get(0);
        if (!passwords.matches(password == null ? "" : password, row == null ? DUMMY_HASH : row.passwordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid email or password");
        }
        jdbc.update("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", row.id());
        return issue(new UserProfile(row.id(), row.email(), row.displayName(), null, row.role(), Instant.now()));
    }

    @Transactional
    public void logout(String token) {
        if (token != null && !token.isBlank()) {
            String tokenHash = hash(token);
            redis.opsForValue().set("auth:revoked:" + tokenHash, "1", Duration.ofSeconds(SESSION_SECONDS));
            redis.delete("auth:session:" + tokenHash);
            jdbc.update("UPDATE user_sessions SET revoked_at=CURRENT_TIMESTAMP WHERE token_hash=? AND revoked_at IS NULL", tokenHash);
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
                if (fields.length == 6) return new UserProfile(decode(fields[0]), decode(fields[1]),
                        decode(fields[2]), decode(fields[3]), decode(fields[4]),
                        fields[5].isEmpty() ? null : Instant.ofEpochMilli(Long.parseLong(fields[5])));
            } catch (RuntimeException corrupt) {
                redis.delete("auth:session:" + tokenHash);
            }
        }
        var users = jdbc.query("""
                SELECT u.id,u.email,u.display_name,u.avatar_url,u.role,u.last_login_at,s.expires_at
                FROM user_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at > CURRENT_TIMESTAMP
                """, (rs, ignored) -> new SessionUser(user(rs), rs.getTimestamp("expires_at").toInstant()), tokenHash);
        if (users.isEmpty()) return null;
        UserProfile profile = users.get(0).profile();
        String value = String.join(":", encode(profile.id()), encode(profile.email()), encode(profile.displayName()),
                encode(profile.avatarUrl()), encode(profile.role()),
                profile.lastLoginAt() == null ? "" : Long.toString(profile.lastLoginAt().toEpochMilli()));
        long cacheSeconds = Math.min(60, Duration.between(Instant.now(), users.get(0).expiresAt()).toSeconds());
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
        jdbc.update("INSERT INTO user_sessions(id,user_id,token_hash,expires_at) VALUES(?,?,?,?)",
                UUID.randomUUID().toString(), user.id(), hash(token),
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

    private record LoginRow(String id, String email, String passwordHash, String displayName, String role) {}
    private record SessionUser(UserProfile profile, Instant expiresAt) {}

    public record UserProfile(String id, String email, String displayName, String avatarUrl, String role,
                              Instant lastLoginAt) {}
    public record AuthResponse(boolean authenticated, UserProfile user, String accessToken, String tokenType,
                               long expiresIn) {}
    public record SessionState(boolean authenticated, UserProfile user) {}
}
