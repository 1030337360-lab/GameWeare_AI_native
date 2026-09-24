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
                                          HttpServletRequest request) {
        return catalog.list(q, tag, identity(request));
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

@Service
class CatalogService {
    private final JdbcTemplate jdbc;

    CatalogService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public List<Map<String, Object>> list(String query, String tag, String userId) {
        if (query != null && query.length() > 100 || tag != null && tag.length() > 80) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Search filter is too long");
        }
        StringBuilder sql = new StringBuilder("""
            SELECT g.id, g.slug, g.title, g.description, g.author_id, g.cover_object_key,
                   g.plays_count, g.likes_count, g.favorites_count, g.published_at, g.created_at,
                   u.display_name AS author,
                   (SELECT GROUP_CONCAT(t.name SEPARATOR '|||') FROM game_tags gt JOIN tags t ON t.id=gt.tag_id WHERE gt.game_id=g.id) AS tag_names,
                   EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=?) AS liked,
                   EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=?) AS favorited
            FROM games g LEFT JOIN users u ON u.id=g.author_id
            WHERE g.publish_status='published' AND g.visibility='public'
            """);
        List<Object> args = new ArrayList<>();
        args.add(userId == null ? "" : userId);
        args.add(userId == null ? "" : userId);
        if (query != null && !query.isBlank()) {
            sql.append(" AND (g.title LIKE ? OR g.description LIKE ? OR EXISTS (SELECT 1 FROM game_tags qgt JOIN tags qt ON qt.id=qgt.tag_id WHERE qgt.game_id=g.id AND qt.name LIKE ?))");
            String search = "%" + query.trim().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
            args.add(search); args.add(search); args.add(search);
        }
        if (tag != null && !tag.isBlank()) {
            sql.append(" AND EXISTS (SELECT 1 FROM game_tags gt JOIN tags t ON t.id=gt.tag_id WHERE gt.game_id=g.id AND LOWER(t.name)=LOWER(?))");
            args.add(tag.trim());
        }
        sql.append(" ORDER BY g.published_at DESC, g.created_at DESC LIMIT 100");
        return jdbc.query(sql.toString(), (rs, n) -> mapGame(rs), args.toArray());
    }

    public List<String> tags() {
        return jdbc.queryForList("""
            SELECT DISTINCT t.name FROM tags t JOIN game_tags gt ON gt.tag_id=t.id
            JOIN games g ON g.id=gt.game_id
            WHERE g.publish_status='published' AND g.visibility='public' ORDER BY t.name
            """, String.class);
    }

    public Map<String, Object> detail(String slug, String userId) {
        List<Map<String, Object>> rows = jdbc.query("""
            SELECT g.id, g.slug, g.title, g.description, g.author_id, g.cover_object_key,
                   g.plays_count, g.likes_count, g.favorites_count, g.published_at, g.created_at,
                   u.display_name AS author,
                   (SELECT GROUP_CONCAT(t.name SEPARATOR '|||') FROM game_tags gt JOIN tags t ON t.id=gt.tag_id WHERE gt.game_id=g.id) AS tag_names,
                   EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=?) AS liked,
                   EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=?) AS favorited
            FROM games g LEFT JOIN users u ON u.id=g.author_id
            WHERE g.slug=? AND g.publish_status='published' AND g.visibility='public' LIMIT 1
            """, (rs, n) -> mapGame(rs), userId == null ? "" : userId, userId == null ? "" : userId, slug);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        return rows.get(0);
    }

    public List<Map<String, Object>> versions(String slug) {
        return jdbc.query("""
            SELECT v.id, v.version_no, v.runtime, v.build_status, v.safety_status, v.entry_file,
                   v.storage_prefix, v.manifest_object_key, v.source_job_id, v.created_at,
                   (g.current_version_id=v.id) AS current_version
            FROM games g JOIN game_versions v ON v.game_id=g.id
            WHERE g.slug=? AND g.publish_status='published' AND g.visibility='public'
            ORDER BY v.version_no DESC
            """, (rs, n) -> {
                Map<String, Object> version = new LinkedHashMap<>();
                version.put("versionId", rs.getString("id"));
                version.put("versionNo", rs.getInt("version_no"));
                version.put("runtime", rs.getString("runtime"));
                version.put("buildStatus", rs.getString("build_status"));
                version.put("safetyStatus", rs.getString("safety_status"));
                version.put("entryFile", rs.getString("entry_file"));
                version.put("storagePrefix", rs.getString("storage_prefix"));
                version.put("manifestUrl", rs.getString("manifest_object_key") == null ? null : "/play/" + slug + "/manifest");
                version.put("sourceJobId", rs.getString("source_job_id"));
                version.put("current", rs.getBoolean("current_version"));
                version.put("createdAt", rs.getTimestamp("created_at").toInstant());
                return version;
            }, slug);
    }

    @Transactional
    public List<Map<String, Object>> switchVersion(String slug, String versionId, String userId) {
        if (versionId == null || versionId.isBlank()) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "versionId required");
        int updated = jdbc.update("""
            UPDATE games g JOIN game_versions v ON v.game_id=g.id
            SET g.current_version_id=v.id
            WHERE g.slug=? AND g.author_id=? AND v.id=?
              AND v.build_status='passed' AND v.safety_status='passed'
            """, slug, userId, versionId);
        if (updated == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game version not found");
        return versions(slug);
    }

    @Transactional
    public Map<String, Object> delete(String slug, String userId) {
        List<String> ids = jdbc.queryForList("SELECT id FROM games WHERE slug=? AND author_id=? AND publish_status<>'deleted'", String.class, slug, userId);
        if (ids.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        jdbc.update("UPDATE games SET publish_status='deleted', visibility='private' WHERE id=?", ids.get(0));
        return Map.of("gameId", ids.get(0), "gameSlug", slug, "deleted", true, "runLogsPreserved", true);
    }

    @Transactional
    public Map<String, Object> remix(String sourceSlug, String userId) {
        List<Map<String, Object>> source = jdbc.queryForList("""
            SELECT title,description,cover_object_key FROM games
            WHERE slug=? AND publish_status='published' AND visibility='public' LIMIT 1
            """, sourceSlug);
        if (source.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String gameId = UUID.randomUUID().toString();
        String slug = "remix-" + UUID.randomUUID().toString().substring(0, 12);
        String title = "Remix of " + source.get(0).get("title");
        if (title.length() > 255) title = title.substring(0, 255);
        String projectId = UUID.randomUUID().toString();
        jdbc.update("""
            INSERT INTO games(id,slug,title,description,author_id,publish_status,visibility,cover_object_key)
            VALUES (?,?,?,? ,?,'draft','private',?)
            """, gameId, slug, title, source.get(0).get("description"), userId, source.get(0).get("cover_object_key"));
        jdbc.update("INSERT INTO create_projects(id,user_id,title,status,game_id) VALUES (?,?,?,'active',?)",
                projectId, userId, title, gameId);
        return Map.of("gameId", gameId, "gameSlug", slug, "projectId", projectId, "title", title, "status", "draft");
    }

    @Transactional
    public Map<String, Object> interact(String slug, String userId, String table, String countColumn, boolean enable) {
        // Table and column names are selected only by controller constants, never by client input.
        List<String> ids = jdbc.queryForList("SELECT id FROM games WHERE slug=? AND publish_status='published' AND visibility='public'", String.class, slug);
        if (ids.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String gameId = ids.get(0);
        if (enable) {
            int inserted = jdbc.update("INSERT IGNORE INTO " + table + " (user_id,game_id) VALUES (?,?)", userId, gameId);
            if (inserted > 0) jdbc.update("UPDATE games SET " + countColumn + "=" + countColumn + "+1 WHERE id=?", gameId);
        } else {
            int deleted = jdbc.update("DELETE FROM " + table + " WHERE user_id=? AND game_id=?", userId, gameId);
            if (deleted > 0) jdbc.update("UPDATE games SET " + countColumn + "=GREATEST(" + countColumn + "-1,0) WHERE id=?", gameId);
        }
        return jdbc.queryForObject("""
            SELECT g.likes_count, g.favorites_count,
                   EXISTS(SELECT 1 FROM game_likes l WHERE l.game_id=g.id AND l.user_id=?) AS liked,
                   EXISTS(SELECT 1 FROM game_favorites f WHERE f.game_id=g.id AND f.user_id=?) AS favorited
            FROM games g WHERE g.id=?
            """, (rs, n) -> Map.<String, Object>of(
                    "gameId", slug,
                    "likes", rs.getLong("likes_count"),
                    "favorites", rs.getLong("favorites_count"),
                    "likedByMe", rs.getBoolean("liked"),
                    "favoritedByMe", rs.getBoolean("favorited")), userId, userId, gameId);
    }

    private Map<String, Object> mapGame(ResultSet rs) throws SQLException {
        String id = rs.getString("id");
        String slug = rs.getString("slug");
        Map<String, Object> game = new LinkedHashMap<>();
        game.put("id", slug);
        game.put("title", rs.getString("title"));
        game.put("author", rs.getString("author") == null ? "Creator" : rs.getString("author"));
        game.put("description", rs.getString("description"));
        String tagNames = rs.getString("tag_names");
        game.put("tags", tagNames == null || tagNames.isBlank() ? List.of() : List.of(tagNames.split("\\|\\|\\|")));
        var published = rs.getTimestamp("published_at");
        if (published == null) published = rs.getTimestamp("created_at");
        game.put("publishedAt", published == null ? Instant.EPOCH : published.toInstant());
        game.put("coverUrl", rs.getString("cover_object_key") == null ? "" : "/games/" + slug + "/cover");
        game.put("plays", rs.getLong("plays_count"));
        game.put("likes", rs.getLong("likes_count"));
        game.put("favorites", rs.getLong("favorites_count"));
        game.put("likedByMe", rs.getBoolean("liked"));
        game.put("favoritedByMe", rs.getBoolean("favorited"));
        game.put("section", "Recently Created");
        return game;
    }
}
