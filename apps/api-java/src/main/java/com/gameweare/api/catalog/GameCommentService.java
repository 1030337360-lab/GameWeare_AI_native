package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.GameCommentMapper;
import com.gameweare.api.catalog.entity.GameCommentEntity;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.server.ResponseStatusException;

@Service
class GameCommentService {
    private final GameCommentMapper comments;
    private final GameCatalogCache cache;

    GameCommentService(GameCommentMapper comments, GameCatalogCache cache) {
        this.comments = comments;
        this.cache = cache;
    }

    Map<String, Object> list(String slug, String userId, int page, int limit) {
        if (page < 0 || page > 1000 || limit < 1 || limit > 50)
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid comment page or limit");
        Map<String, Object> game = publicGame(slug);
        List<Map<String, Object>> rows = comments.list((String) game.get("id"), limit + 1, page * limit)
                .stream().map(row -> mapComment(row, userId)).toList();
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
        comments.insert(id, gameId, userId, normalized);
        comments.incrementCount(gameId);
        invalidateAfterCommit(slug);
        return mapComment(comments.findById(id), userId);
    }

    @Transactional
    Map<String, Object> delete(String slug, String commentId, String userId) {
        String gameId = (String) publicGame(slug).get("id");
        if (comments.softDelete(commentId, gameId, userId) == 0)
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Comment not found");
        comments.decrementCount(gameId);
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
        Map<String, Object> game = comments.findPublicGame(slug);
        if (game == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Game not found");
        return game;
    }

    private Map<String, Object> mapComment(GameCommentEntity row, String userId) {
        Map<String, Object> comment = new LinkedHashMap<>();
        comment.put("id", row.id());
        comment.put("userId", row.userId());
        comment.put("author", row.displayName());
        comment.put("content", row.content());
        comment.put("createdAt", row.createdAt().toInstant());
        comment.put("mine", userId != null && userId.equals(row.userId()));
        return comment;
    }
}
