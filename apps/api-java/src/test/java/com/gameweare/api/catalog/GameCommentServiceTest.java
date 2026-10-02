package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.GameCommentMapper;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class GameCommentServiceTest {
    private final GameCommentMapper db = mock(GameCommentMapper.class);
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
        when(db.findPublicGame("game")).thenReturn(Map.of("id", "game-id", "comments_count", 2L));
        when(db.softDelete("comment-id", "game-id", "owner")).thenReturn(1);
        service.delete("game", "comment-id", "owner");
        verify(db).decrementCount("game-id");
        verify(cache).invalidate("game");
    }
}
