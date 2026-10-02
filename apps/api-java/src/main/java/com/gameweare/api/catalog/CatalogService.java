package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.CatalogMapper;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

@Service
class CatalogService {
    private final CatalogMapper games;
    private final GameCatalogCache cache;
    private final GameTrendingService trending;

    @Autowired
    CatalogService(CatalogMapper games, GameCatalogCache cache, GameTrendingService trending) {
        this.games = games;
        this.cache = cache;
        this.trending = trending;
    }

    CatalogService(CatalogMapper games) {
        this.games = games;
        this.cache = null;
        this.trending = null;
    }

    public List<Map<String, Object>> list(String query, String tag, String userId) {
        return list(query, tag, "latest", userId);
    }

    public List<Map<String, Object>> list(String query, String tag, String sort, String userId) {
        if (query != null && query.length() > 100 || tag != null && tag.length() > 80)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Search filter is too long");
        if (!List.of("latest", "likes").contains(sort))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "sort must be latest or likes");
        String search = query == null || query.isBlank() ? null
                : "%" + query.trim().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%";
        return games.list(userId == null ? "" : userId, search,
                tag == null || tag.isBlank() ? null : tag.trim(), sort).stream().map(this::mapGame).toList();
    }

    public List<String> tags() {
        return games.tags();
    }

    public Map<String, Object> detail(String slug, String userId) {
        if (cache != null && !cache.mightContain(slug))
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        if (games.publicCount(slug) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        Map<String, Object> game = cache == null ? publicDetail(slug)
                : cache.publicGame(slug, () -> publicDetail(slug));
        if (game == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        Map<String, Object> out = new LinkedHashMap<>(game);
        if (userId != null) {
            Map<String, Object> flags = games.interactionFlags(userId, slug);
            if (flags != null) {
                out.put("likedByMe", truth(flags.get("liked")));
                out.put("favoritedByMe", truth(flags.get("favorited")));
            }
        }
        return out;
    }

    private Map<String, Object> publicDetail(String slug) {
        Map<String, Object> row = games.publicDetail(slug);
        if (row == null) return null;
        Map<String, Object> game = mapGame(row);
        game.put("publishedAt", game.get("publishedAt").toString());
        return game;
    }

    public List<Map<String, Object>> versions(String slug) {
        return games.versions(slug).stream().map(row -> {
            Map<String, Object> version = new LinkedHashMap<>();
            version.put("versionId", row.get("id"));
            version.put("versionNo", number(row, "version_no"));
            version.put("runtime", row.get("runtime"));
            version.put("buildStatus", row.get("build_status"));
            version.put("safetyStatus", row.get("safety_status"));
            version.put("entryFile", row.get("entry_file"));
            version.put("storagePrefix", row.get("storage_prefix"));
            version.put("manifestUrl", row.get("manifest_object_key") == null ? null : "/play/" + slug + "/manifest");
            version.put("sourceJobId", row.get("source_job_id"));
            version.put("current", truth(row.get("current_version")));
            version.put("createdAt", instant(row.get("created_at")));
            return version;
        }).toList();
    }

    @Transactional
    public List<Map<String, Object>> switchVersion(String slug, String versionId, String userId) {
        if (versionId == null || versionId.isBlank())
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "versionId required");
        if (games.switchVersion(slug, versionId, userId) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game version not found");
        invalidateAfterCommit(slug);
        return versions(slug);
    }

    @Transactional
    public Map<String, Object> delete(String slug, String userId) {
        String id = games.ownedGameId(slug, userId);
        if (id == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        games.softDelete(id);
        invalidateAfterCommit(slug);
        trendAfterCommit(id);
        return Map.of("gameId", id, "gameSlug", slug, "deleted", true, "runLogsPreserved", true);
    }

    @Transactional
    public Map<String, Object> remix(String sourceSlug, String userId) {
        Map<String, Object> source = games.remixSource(sourceSlug);
        if (source == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        String gameId = UUID.randomUUID().toString();
        String slug = "remix-" + UUID.randomUUID().toString().substring(0, 12);
        String title = "Remix of " + source.get("title");
        if (title.length() > 255) title = title.substring(0, 255);
        String projectId = UUID.randomUUID().toString();
        games.insertRemix(gameId, slug, title, (String) source.get("description"), userId,
                (String) source.get("cover_object_key"));
        games.insertRemixProject(projectId, userId, title, gameId);
        return Map.of("gameId", gameId, "gameSlug", slug, "projectId", projectId, "title", title, "status", "draft");
    }

    @Transactional
    public Map<String, Object> interact(String slug, String userId, String table, String countColumn, boolean enable) {
        // Only the two controller-selected types are accepted; SQL identifiers never come from a request.
        if (!("game_likes".equals(table) && "likes_count".equals(countColumn))
                && !("game_favorites".equals(table) && "favorites_count".equals(countColumn)))
            throw new IllegalArgumentException("Unsupported game interaction");
        String gameId = games.publicGameId(slug);
        if (gameId == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        if ("game_likes".equals(table)) {
            if (enable) {
                if (games.like(userId, gameId) > 0) games.incrementLikes(gameId);
            } else if (games.unlike(userId, gameId) > 0) games.decrementLikes(gameId);
        } else {
            if (enable) {
                if (games.favorite(userId, gameId) > 0) games.incrementFavorites(gameId);
            } else if (games.unfavorite(userId, gameId) > 0) games.decrementFavorites(gameId);
        }
        invalidateAfterCommit(slug);
        trendAfterCommit(gameId);
        Map<String, Object> row = games.interactionSummary(userId, gameId);
        return Map.of("gameId", slug, "likes", number(row, "likes_count"),
                "favorites", number(row, "favorites_count"),
                "likedByMe", truth(row.get("liked")), "favoritedByMe", truth(row.get("favorited")));
    }

    private Map<String, Object> mapGame(Map<String, Object> row) {
        String slug = (String) row.get("slug");
        Map<String, Object> game = new LinkedHashMap<>();
        game.put("id", slug);
        game.put("title", row.get("title"));
        game.put("author", row.get("author") == null ? "Creator" : row.get("author"));
        game.put("creatorId", row.get("author_id"));
        game.put("description", row.get("description"));
        String tagNames = (String) row.get("tag_names");
        game.put("tags", tagNames == null || tagNames.isBlank() ? List.of() : List.of(tagNames.split("\\|\\|\\|")));
        Object published = row.get("published_at") == null ? row.get("created_at") : row.get("published_at");
        game.put("publishedAt", published == null ? Instant.EPOCH : instant(published));
        game.put("coverUrl", "/games/" + slug + "/cover");
        game.put("plays", number(row, "plays_count"));
        game.put("likes", number(row, "likes_count"));
        game.put("comments", number(row, "comments_count"));
        game.put("favorites", number(row, "favorites_count"));
        game.put("likedByMe", truth(row.get("liked")));
        game.put("favoritedByMe", truth(row.get("favorited")));
        game.put("section", "Recently Created");
        return game;
    }

    private static long number(Map<String, Object> row, String column) {
        return ((Number) row.get(column)).longValue();
    }

    private static boolean truth(Object value) {
        return value instanceof Boolean flag ? flag : value instanceof Number number && number.intValue() != 0;
    }

    private static Instant instant(Object value) {
        if (value instanceof Timestamp timestamp) return timestamp.toInstant();
        if (value instanceof LocalDateTime local) return local.toInstant(ZoneOffset.UTC);
        if (value instanceof java.util.Date date) return date.toInstant();
        throw new IllegalStateException("Unsupported SQL date type: " + value.getClass());
    }

    private void invalidateAfterCommit(String slug) {
        if (cache == null) return;
        if (TransactionSynchronizationManager.isSynchronizationActive())
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { cache.invalidate(slug); }
            });
        else cache.invalidate(slug);
    }

    private void trendAfterCommit(String gameId) {
        if (trending == null) return;
        if (TransactionSynchronizationManager.isSynchronizationActive())
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { trending.refresh(gameId); }
            });
        else trending.refresh(gameId);
    }
}
