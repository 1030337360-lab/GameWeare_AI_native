package com.gameweare.api.auth;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.time.Duration;
import java.util.Base64;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
public class GoogleOAuthService {
    private static final String STATE_PREFIX = "auth:google:state:";
    private static final URI AUTHORIZE = URI.create("https://accounts.google.com/o/oauth2/v2/auth");
    private static final URI TOKEN = URI.create("https://oauth2.googleapis.com/token");
    private static final URI USERINFO = URI.create("https://www.googleapis.com/oauth2/v3/userinfo");
    private final String clientId;
    private final String clientSecret;
    private final String redirectUri;
    private final String webOrigin;
    private final long starterTokens;
    private final StringRedisTemplate redis;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transaction;
    private final AuthService auth;
    private final ObjectMapper json;
    private final SecureRandom random = new SecureRandom();
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NEVER).build();

    public GoogleOAuthService(@Value("${GOOGLE_CLIENT_ID:}") String clientId,
                              @Value("${GOOGLE_CLIENT_SECRET:}") String clientSecret,
                              @Value("${GOOGLE_REDIRECT_URI:http://localhost:8080/auth/google/callback}") String redirectUri,
                              @Value("${yahaha.web-origin:http://localhost:1314}") String webOrigin,
                              @Value("${yahaha.billing.starter-tokens:100000}") long starterTokens,
                              StringRedisTemplate redis, JdbcTemplate jdbc, TransactionTemplate transaction,
                              AuthService auth, ObjectMapper json) {
        this.clientId = clientId; this.clientSecret = clientSecret; this.redirectUri = redirectUri;
        this.webOrigin = webOrigin; this.starterTokens = starterTokens; this.redis = redis;
        this.jdbc = jdbc; this.transaction = transaction; this.auth = auth; this.json = json;
    }

    public URI start(String linkingUserId) {
        requireConfigured();
        byte[] nonce = new byte[32];
        random.nextBytes(nonce);
        String state = Base64.getUrlEncoder().withoutPadding().encodeToString(nonce);
        Boolean saved = redis.opsForValue().setIfAbsent(STATE_PREFIX + state,
                linkingUserId == null ? "login" : "link:" + linkingUserId, Duration.ofMinutes(10));
        if (!Boolean.TRUE.equals(saved)) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "OAuth state unavailable");
        String query = "client_id=" + encode(clientId) + "&redirect_uri=" + encode(redirectUri)
                + "&response_type=code&scope=" + encode("openid email profile")
                + "&state=" + encode(state) + "&prompt=select_account";
        return URI.create(AUTHORIZE + "?" + query);
    }

    public URI callback(String code, String state) {
        requireConfigured();
        if (state == null || !state.matches("[A-Za-z0-9_-]{32,64}") || code == null || code.isBlank() || code.length() > 4096)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid OAuth callback");
        // GETDEL makes a state single-use even when callbacks race on different API replicas.
        String mode = redis.opsForValue().getAndDelete(STATE_PREFIX + state);
        if (mode == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid or expired OAuth state");
        GoogleIdentity identity = fetchIdentity(code);
        AuthService.AuthResponse session = transaction.execute(status -> signIn(identity, mode));
        return URI.create(webOrigin.replaceAll("/+$", "") + "/auth/callback#access_token=" + encode(session.accessToken()));
    }

    private AuthService.AuthResponse signIn(GoogleIdentity identity, String mode) {
        List<String> mapped = jdbc.queryForList("SELECT user_id FROM oauth_accounts WHERE provider='google' AND provider_subject=?",
                String.class, identity.subject());
        String userId;
        if (mode.startsWith("link:")) {
            userId = mode.substring(5);
            if (jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE id=?", Integer.class, userId) == 0)
                throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Linking user no longer exists");
            if (!mapped.isEmpty() && !mapped.get(0).equals(userId))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Google account is linked elsewhere");
            List<String> emailOwners = jdbc.queryForList("SELECT id FROM users WHERE email=?", String.class, identity.email());
            if (!emailOwners.isEmpty() && !emailOwners.get(0).equals(userId))
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Google email belongs to another account");
        } else if ("login".equals(mode)) {
            if (!mapped.isEmpty()) userId = mapped.get(0);
            else {
                // Do not silently take over an unverified local email account.
                if (jdbc.queryForObject("SELECT COUNT(*) FROM users WHERE email=?", Integer.class, identity.email()) != 0)
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Email already registered; sign in and link Google explicitly");
                userId = UUID.randomUUID().toString();
                try {
                    jdbc.update("INSERT INTO users(id,email,password_hash,display_name,avatar_url,role,last_login_at) VALUES(?,?,NULL,?,?,'user',CURRENT_TIMESTAMP)",
                            userId, identity.email(), identity.name(), identity.picture());
                } catch (DataIntegrityViolationException race) {
                    throw new ResponseStatusException(HttpStatus.CONFLICT, "Email was registered concurrently", race);
                }
                jdbc.update("INSERT INTO token_accounts(user_id,balance,reserved,version) VALUES(?,?,0,0)", userId, starterTokens);
                if (starterTokens > 0) jdbc.update("INSERT INTO token_ledger(id,user_id,job_id,entry_type,amount) VALUES(?,?,?,?,?)",
                        UUID.randomUUID().toString(), userId, userId, "GRANT", starterTokens);
            }
        } else throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid OAuth state");
        if (mapped.isEmpty()) {
            try {
                jdbc.update("INSERT INTO oauth_accounts(provider,provider_subject,user_id,provider_email) VALUES('google',?,?,?)",
                        identity.subject(), userId, identity.email());
            } catch (DataIntegrityViolationException race) {
                throw new ResponseStatusException(HttpStatus.CONFLICT, "Google account was linked concurrently", race);
            }
        } else {
            jdbc.update("UPDATE oauth_accounts SET provider_email=? WHERE provider='google' AND provider_subject=?",
                    identity.email(), identity.subject());
        }
        jdbc.update("UPDATE users SET last_login_at=CURRENT_TIMESTAMP,avatar_url=COALESCE(?,avatar_url) WHERE id=?",
                identity.picture(), userId);
        var users = jdbc.query("SELECT id,email,display_name,avatar_url,role,last_login_at FROM users WHERE id=?",
                (rs, ignored) -> AuthService.user(rs), userId);
        return auth.issue(users.get(0));
    }

    private GoogleIdentity fetchIdentity(String code) {
        try {
            String form = "code=" + encode(code) + "&client_id=" + encode(clientId)
                    + "&client_secret=" + encode(clientSecret) + "&redirect_uri=" + encode(redirectUri)
                    + "&grant_type=authorization_code";
            HttpRequest tokenRequest = HttpRequest.newBuilder(TOKEN).timeout(Duration.ofSeconds(10))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(form)).build();
            HttpResponse<String> tokenResponse = http.send(tokenRequest, HttpResponse.BodyHandlers.ofString());
            if (tokenResponse.statusCode() != 200) throw new IllegalStateException("Google token exchange failed");
            JsonNode tokenJson = json.readTree(tokenResponse.body());
            String accessToken = tokenJson.path("access_token").asText("");
            if (accessToken.isBlank()) throw new IllegalStateException("Google access token missing");
            HttpRequest userRequest = HttpRequest.newBuilder(USERINFO).timeout(Duration.ofSeconds(10))
                    .header("Authorization", "Bearer " + accessToken).GET().build();
            HttpResponse<String> userResponse = http.send(userRequest, HttpResponse.BodyHandlers.ofString());
            if (userResponse.statusCode() != 200) throw new IllegalStateException("Google user info failed");
            JsonNode user = json.readTree(userResponse.body());
            String subject = user.path("sub").asText("");
            String email = user.path("email").asText("").strip().toLowerCase(java.util.Locale.ROOT);
            if (subject.isBlank() || subject.length() > 255 || email.isBlank() || email.length() > 254
                    || !user.path("email_verified").asBoolean(false))
                throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Google email is not verified");
            String name = user.path("name").asText("").strip();
            if (name.isBlank()) name = email.substring(0, email.indexOf('@'));
            if (name.length() > 120) name = name.substring(0, 120);
            String picture = user.path("picture").asText("");
            if (picture.length() > 1024) picture = "";
            return new GoogleIdentity(subject, email, name, picture.isBlank() ? null : picture);
        } catch (ResponseStatusException e) { throw e; }
        catch (Exception e) { throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Google authentication failed", e); }
    }

    private void requireConfigured() {
        if (clientId.isBlank() || clientSecret.isBlank())
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Google OAuth is not configured");
    }

    private static String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
    private record GoogleIdentity(String subject, String email, String name, String picture) {}
}
