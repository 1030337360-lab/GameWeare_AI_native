package com.gameweare.api.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import com.gameweare.api.voucher.VoucherStageMetrics;

@Component
public class AuthFilter extends OncePerRequestFilter {
    private final AuthService auth;
    private final VoucherStageMetrics metrics;

    public AuthFilter(AuthService auth, VoucherStageMetrics metrics) {
        this.auth = auth;
        this.metrics = metrics;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        try {
            String token = bearer(request);
            if (token != null) {
                var user = metrics.time("auth.token_lookup", () -> auth.findUserByToken(token));
                if (user != null) {
                    request.setAttribute("userId", user.id());
                    request.setAttribute("authUser", user);
                    SecurityContextHolder.getContext().setAuthentication(
                            new UsernamePasswordAuthenticationToken(user.id(), null,
                                    java.util.List.of(new SimpleGrantedAuthority("ROLE_" + user.role().toUpperCase()))));
                }
            }
            chain.doFilter(request, response);
        } finally {
            SecurityContextHolder.clearContext();
        }
    }

    public static String bearer(HttpServletRequest request) {
        String value = request.getHeader("Authorization");
        if (value == null || !value.regionMatches(true, 0, "Bearer ", 0, 7)) return null;
        String token = value.substring(7).trim();
        return token.isEmpty() ? null : token;
    }
}
