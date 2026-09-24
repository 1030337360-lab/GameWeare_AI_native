package com.gameweare.api.catalog;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CatalogServiceTest {
    @Test
    void duplicateLikeDoesNotIncreaseCounter() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), eq(String.class), eq("game"))).thenReturn(List.of("game-id"));
        when(jdbc.update(eq("INSERT IGNORE INTO game_likes (user_id,game_id) VALUES (?,?)"), eq("user-id"), eq("game-id")))
                .thenReturn(0);
        when(jdbc.queryForObject(anyString(), any(org.springframework.jdbc.core.RowMapper.class),
                eq("user-id"), eq("user-id"), eq("game-id")))
                .thenReturn(Map.of("gameId", "game", "likes", 1L, "favorites", 0L,
                        "likedByMe", true, "favoritedByMe", false));

        Map<String, Object> result = new CatalogService(jdbc).interact("game", "user-id", "game_likes", "likes_count", true);

        assertEquals(1L, result.get("likes"));
        verify(jdbc, never()).update(eq("UPDATE games SET likes_count=likes_count+1 WHERE id=?"), eq("game-id"));
    }
}
