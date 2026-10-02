package com.gameweare.api.catalog;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

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
