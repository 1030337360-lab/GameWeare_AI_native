package com.gameweare.api.catalog;

import jakarta.servlet.http.HttpServletRequest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/games")
public class GameCatalogController {
    private final CatalogService catalog;

    public GameCatalogController(CatalogService catalog) { this.catalog = catalog; }

    @GetMapping
    public List<Map<String, Object>> list(@RequestParam(required = false) String q,
                                          @RequestParam(required = false) String tag,
                                          @RequestParam(defaultValue = "latest") String sort,
                                          HttpServletRequest request) {
        return catalog.list(q, tag, sort, identity(request));
    }

    @GetMapping("/tags")
    public List<String> tags() { return catalog.tags(); }

    @GetMapping("/{id}")
    public Map<String, Object> detail(@PathVariable String id, HttpServletRequest request) {
        return catalog.detail(id, identity(request));
    }

    @GetMapping("/{id}/versions")
    public List<Map<String, Object>> versions(@PathVariable String id) { return catalog.versions(id); }

    @PostMapping("/{id}/versions/switch")
    public List<Map<String, Object>> switchVersion(@PathVariable String id, @RequestBody Map<String, String> body,
                                                    HttpServletRequest request) {
        return catalog.switchVersion(id, body.get("versionId"), requiredIdentity(request));
    }

    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable String id, HttpServletRequest request) {
        return catalog.delete(id, requiredIdentity(request));
    }

    @PostMapping("/{id}/remix")
    public Map<String, Object> remix(@PathVariable String id, HttpServletRequest request) {
        return catalog.remix(id, requiredIdentity(request));
    }

    @PutMapping("/{id}/like")
    public Map<String, Object> like(@PathVariable String id, HttpServletRequest request) {
        return catalog.interact(id, requiredIdentity(request), "game_likes", "likes_count", true);
    }

    @DeleteMapping("/{id}/like")
    public Map<String, Object> unlike(@PathVariable String id, HttpServletRequest request) {
        return catalog.interact(id, requiredIdentity(request), "game_likes", "likes_count", false);
    }

    @PutMapping("/{id}/favorite")
    public Map<String, Object> favorite(@PathVariable String id, HttpServletRequest request) {
        return catalog.interact(id, requiredIdentity(request), "game_favorites", "favorites_count", true);
    }

    @DeleteMapping("/{id}/favorite")
    public Map<String, Object> unfavorite(@PathVariable String id, HttpServletRequest request) {
        return catalog.interact(id, requiredIdentity(request), "game_favorites", "favorites_count", false);
    }

    static String identity(HttpServletRequest request) {
        Object value = request.getAttribute("userId");
        return value == null ? null : value.toString();
    }

    static String requiredIdentity(HttpServletRequest request) {
        String id = identity(request);
        if (id == null || id.isBlank()) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Login required");
        return id;
    }
}
