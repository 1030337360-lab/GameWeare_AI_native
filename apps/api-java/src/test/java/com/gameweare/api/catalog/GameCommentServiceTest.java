package com.gameweare.api.catalog;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class GameCommentServiceTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final GameCatalogCache cache = mock(GameCatalogCache.class);
    private final GameCommentService service = new GameCommentService(db, cache);

    @Test
    void rejectsEmptyCommentBeforeAnyDatabaseWrite() {
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.post("game", "user", "   "));
        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
        verifyNoInteractions(db);
    }

    @Test
    void onlyCommentOwnerCanDeleteAndCountChangesOnce() {
        when(db.queryForList(anyString(), eq("game")))
                .thenReturn(List.of(Map.of("id", "game-id", "comments_count", 2L)));
        when(db.update(anyString(), eq("comment-id"), eq("game-id"), eq("owner"))).thenReturn(1);
        service.delete("game", "comment-id", "owner");
        verify(db).update("UPDATE games SET comments_count=GREATEST(comments_count-1,0) WHERE id=?", "game-id");
        verify(cache).invalidate("game");
    }
}
