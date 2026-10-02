package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.CatalogMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CatalogServiceTest {
    @Test
    void likesSortSelectsMapperOrder() {
        CatalogMapper mapper = mock(CatalogMapper.class);
        when(mapper.list("", null, null, "likes")).thenReturn(List.of());
        new CatalogService(mapper).list(null, null, "likes", null);
        verify(mapper).list("", null, null, "likes");
    }

    @Test
    void duplicateLikeDoesNotIncreaseCounter() {
        CatalogMapper mapper = mock(CatalogMapper.class);
        when(mapper.publicGameId("game")).thenReturn("game-id");
        when(mapper.interactionSummary("user-id", "game-id")).thenReturn(Map.of(
                "likes_count", 1L, "favorites_count", 0L, "liked", true, "favorited", false));

        Map<String, Object> result = new CatalogService(mapper).interact("game", "user-id", "game_likes", "likes_count", true);

        assertEquals(1L, result.get("likes"));
        verify(mapper, never()).incrementLikes("game-id");
    }
}
