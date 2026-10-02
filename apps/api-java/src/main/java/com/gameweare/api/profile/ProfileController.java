package com.gameweare.api.profile;

import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/profile")
public class ProfileController {
    private final ProfileService profile;
    public ProfileController(ProfileService profile) { this.profile = profile; }

    @GetMapping("/activity")
    public Map<String, Object> activity(HttpServletRequest request) { return profile.activity(user(request)); }

    @GetMapping("/projects/{id}")
    public Map<String, Object> project(@PathVariable String id, HttpServletRequest request) {
        return profile.project(user(request), id);
    }

    private String user(HttpServletRequest request) {
        Object id = request.getAttribute("userId");
        if (id == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Login required");
        return id.toString();
    }
}
