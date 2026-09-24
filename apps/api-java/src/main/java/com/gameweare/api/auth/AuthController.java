package com.gameweare.api.auth;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.http.ResponseEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@RestController
@RequestMapping("/auth")
public class AuthController {
    private final AuthService auth;
    private final GoogleOAuthService google;

    public AuthController(AuthService auth, GoogleOAuthService google) { this.auth = auth; this.google = google; }

    @GetMapping("/google/start")
    public ResponseEntity<Void> googleStart() {
        URI destination = google.start(null);
        return ResponseEntity.status(302).location(destination)
                .header(HttpHeaders.SET_COOKIE, stateCookie(destination).toString()).build();
    }

    @GetMapping("/google/link/start")
    public ResponseEntity<String> googleLinkStart(@RequestAttribute("userId") String userId) {
        URI destination = google.start(userId);
        return ResponseEntity.ok().header(HttpHeaders.SET_COOKIE, stateCookie(destination).toString())
                .body(destination.toString());
    }

    @GetMapping("/google/callback")
    public ResponseEntity<Void> googleCallback(@org.springframework.web.bind.annotation.RequestParam String code,
                                               @org.springframework.web.bind.annotation.RequestParam String state,
                                               @org.springframework.web.bind.annotation.CookieValue(value = "gameweare_google_state", required = false) String cookie) {
        if (cookie == null || !MessageDigest.isEqual(state.getBytes(StandardCharsets.UTF_8), cookie.getBytes(StandardCharsets.UTF_8)))
            throw new org.springframework.web.server.ResponseStatusException(org.springframework.http.HttpStatus.BAD_REQUEST, "Invalid OAuth browser state");
        return ResponseEntity.status(302).location(google.callback(code, state))
                .header(HttpHeaders.SET_COOKIE, ResponseCookie.from("gameweare_google_state", "")
                        .httpOnly(true).path("/auth/google").maxAge(0).build().toString()).build();
    }

    private ResponseCookie stateCookie(URI destination) {
        String state = java.util.Arrays.stream(destination.getRawQuery().split("&"))
                .filter(item -> item.startsWith("state=")).findFirst().orElseThrow().substring(6);
        return ResponseCookie.from("gameweare_google_state", state).httpOnly(true)
                .secure(destination.toString().contains("redirect_uri=https%3A"))
                .sameSite("Lax").path("/auth/google").maxAge(600).build();
    }

    @PostMapping("/register")
    public AuthService.AuthResponse register(@RequestBody RegisterRequest request) {
        return auth.register(request.email(), request.password(), request.displayName());
    }

    @PostMapping("/login")
    public AuthService.AuthResponse login(@RequestBody LoginRequest request) {
        return auth.login(request.email(), request.password());
    }

    @PostMapping("/logout")
    public AuthService.SessionState logout(HttpServletRequest request) {
        auth.logout(AuthFilter.bearer(request));
        return new AuthService.SessionState(false, null);
    }

    @GetMapping("/session")
    public AuthService.SessionState session(HttpServletRequest request) {
        var user = (AuthService.UserProfile) request.getAttribute("authUser");
        return new AuthService.SessionState(user != null, user);
    }

    public record RegisterRequest(String email, String password, String displayName) {}
    public record LoginRequest(String email, String password) {}
}
