package com.gameweare.api.catalog;

import jakarta.servlet.http.HttpServletRequest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/games/{slug}/comments")
public class GameCommentController {
    private final GameCommentService comments;

    public GameCommentController(GameCommentService comments) { this.comments = comments; }

    public record CommentInput(String content) {}

    @GetMapping
    public Map<String, Object> list(@PathVariable String slug,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int limit,
            HttpServletRequest request) {
        return comments.list(slug, GameCatalogController.identity(request), page, limit);
    }

    @PostMapping
    public Map<String, Object> post(@PathVariable String slug,
            @RequestBody CommentInput input, HttpServletRequest request) {
        return comments.post(slug, GameCatalogController.requiredIdentity(request),
                input == null ? null : input.content());
    }

    @DeleteMapping("/{commentId}")
    public Map<String, Object> delete(@PathVariable String slug, @PathVariable String commentId,
            HttpServletRequest request) {
        return comments.delete(slug, commentId, GameCatalogController.requiredIdentity(request));
    }
}

@Service
class GameCommentService {
    private final JdbcTemplate db;
    private final GameCatalogCache cache;

    GameCommentService(JdbcTemplate db, GameCatalogCache cache) { this.db = db; this.cache = cache; }

    Map<String, Object> list(String slug, String userId, int page, int limit) {
        if (page < 0 || page > 1000 || limit < 1 || limit > 50)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid comment page or limit");
        Map<String, Object> game = publicGame(slug);
        List<Map<String, Object>> rows = db.query("""
                SELECT c.id,c.user_id,c.content,c.created_at,u.display_name
                FROM game_comments c JOIN users u ON u.id=c.user_id
                WHERE c.game_id=? AND c.deleted_at IS NULL
                ORDER BY c.created_at DESC,c.id DESC LIMIT ? OFFSET ?
                """, (rs, ignored) -> mapComment(rs, userId), game.get("id"), limit + 1, page * limit);
        boolean hasMore = rows.size() > limit;
        if (hasMore) rows = new ArrayList<>(rows.subList(0, limit));
        return Map.of("items", rows, "hasMore", hasMore,
                "page", page, "total", ((Number) game.get("comments_count")).longValue());
    }

    @Transactional
    Map<String, Object> post(String slug, String userId, String content) {
        if (content == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Comment is required");
        String normalized = content.replace("\r\n", "\n").replace('\r', '\n').strip();
        if (normalized.isEmpty() || normalized.length() > 1000 || normalized.chars()
                .anyMatch(ch -> Character.isISOControl(ch) && ch != '\n' && ch != '\t'))
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Comment must be 1–1000 readable characters");
        String gameId = (String) publicGame(slug).get("id");
        String id = UUID.randomUUID().toString();
        db.update("INSERT INTO game_comments(id,game_id,user_id,content) VALUES(?,?,?,?)",
                id, gameId, userId, normalized);
        db.update("UPDATE games SET comments_count=comments_count+1 WHERE id=?", gameId);
        invalidateAfterCommit(slug);
        return db.queryForObject("""
                SELECT c.id,c.user_id,c.content,c.created_at,u.display_name
                FROM game_comments c JOIN users u ON u.id=c.user_id WHERE c.id=?
                """, (rs, ignored) -> mapComment(rs, userId), id);
    }

    @Transactional
    Map<String, Object> delete(String slug, String commentId, String userId) {
        String gameId = (String) publicGame(slug).get("id");
        int changed = db.update("""
                UPDATE game_comments SET deleted_at=NOW(6)
                WHERE id=? AND game_id=? AND user_id=? AND deleted_at IS NULL
                """, commentId, gameId, userId);
        if (changed == 0) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Comment not found");
        db.update("UPDATE games SET comments_count=GREATEST(comments_count-1,0) WHERE id=?", gameId);
        invalidateAfterCommit(slug);
        return Map.of("commentId", commentId, "deleted", true);
    }

    private void invalidateAfterCommit(String slug) {
        if (TransactionSynchronizationManager.isSynchronizationActive())
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override public void afterCommit() { cache.invalidate(slug); }
            });
        else cache.invalidate(slug);
    }

    private Map<String, Object> publicGame(String slug) {
        List<Map<String, Object>> rows = db.queryForList("""
                SELECT id,comments_count FROM games
                WHERE slug=? AND publish_status='published' AND visibility='public'
                """, slug);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        return rows.get(0);
    }

    private Map<String, Object> mapComment(ResultSet rs, String userId) throws SQLException {
        Map<String, Object> comment = new LinkedHashMap<>();
        comment.put("id", rs.getString("id"));
        comment.put("userId", rs.getString("user_id"));
        comment.put("author", rs.getString("display_name"));
        comment.put("content", rs.getString("content"));
        comment.put("createdAt", rs.getTimestamp("created_at").toInstant());
        comment.put("mine", userId != null && userId.equals(rs.getString("user_id")));
        return comment;
    }
}
