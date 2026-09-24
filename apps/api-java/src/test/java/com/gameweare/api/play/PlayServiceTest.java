package com.gameweare.api.play;

import io.minio.MinioClient;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** Play events: 30-minute dedupe windows keep the plays counter race-free. */
class PlayServiceTest {
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final PlayService service = new PlayService(jdbc, mock(MinioClient.class), "bucket");

    private PlayController.PlayEvent event(String type, String anonymousId) {
        return new PlayController.PlayEvent("game-slug", type, anonymousId, Instant.now(), null, null, Map.of());
    }

    @Test
    void invalidEventTypeIsRejected() {
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.event(event("cheat", null), "u1")));
    }

    @Test
    void unknownGameIsRejected() {
        when(jdbc.queryForList(anyString(), eq(String.class), eq("game-slug"))).thenReturn(List.of());

        assertEquals(HttpStatus.NOT_FOUND, status(() -> service.event(event("game_start", null), "u1")));
    }

    @Test
    void firstStartInWindowCountsThePlay() {
        publishedGame();
        when(jdbc.update(contains("play_count_dedupe"), eq("game-1"), eq("u:u1"), any(Timestamp.class))).thenReturn(1);

        Map<String, Object> out = service.event(event("game_start", null), "u1");

        assertTrue((Boolean) out.get("counted"));
        verify(jdbc).update("UPDATE games SET plays_count=plays_count+1 WHERE id=?", "game-1");
        verify(jdbc).update(contains("play_events"), any(), eq("u1"), isNull(), eq("game-1"), eq("game_start"));
    }

    @Test
    void duplicateStartInWindowIsNotCountedAgain() {
        publishedGame();
        when(jdbc.update(contains("play_count_dedupe"), eq("game-1"), eq("u:u1"), any(Timestamp.class))).thenReturn(0);

        Map<String, Object> out = service.event(event("game_view", null), "u1");

        assertFalse((Boolean) out.get("counted"));
        verify(jdbc, never()).update("UPDATE games SET plays_count=plays_count+1 WHERE id=?", "game-1");
    }

    @Test
    void anonymousIdentityUsesAnonymousPrefix() {
        publishedGame();
        when(jdbc.update(contains("play_count_dedupe"), eq("game-1"), eq("a:anon-42"), any(Timestamp.class))).thenReturn(1);

        Map<String, Object> out = service.event(event("game_start", "anon-42"), null);

        assertTrue((Boolean) out.get("counted"));
        verify(jdbc).update(contains("play_events"), any(), isNull(), eq("anon-42"), eq("game-1"), eq("game_start"));
    }

    @Test
    void loggedInUserOverridesAnonymousIdentity() {
        publishedGame();
        when(jdbc.update(contains("play_count_dedupe"), eq("game-1"), eq("u:u1"), any(Timestamp.class))).thenReturn(1);

        service.event(event("game_start", "anon-42"), "u1");

        verify(jdbc).update(contains("play_events"), any(), eq("u1"), isNull(), eq("game-1"), eq("game_start"));
    }

    @Test
    void eventsWithoutIdentityAreStoredButNotCounted() {
        publishedGame();

        Map<String, Object> out = service.event(event("game_load_error", null), null);

        assertFalse((Boolean) out.get("counted"));
        verify(jdbc, never()).update(contains("play_count_dedupe"), any(), any(), any(Timestamp.class));
        verify(jdbc, never()).update("UPDATE games SET plays_count=plays_count+1 WHERE id=?", "game-1");
    }

    @Test
    void oversizedAnonymousIdIsRejected() {
        publishedGame();

        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.event(event("game_start", "x".repeat(65)), null)));
    }

    private void publishedGame() {
        when(jdbc.queryForList(anyString(), eq(String.class), eq("game-slug"))).thenReturn(List.of("game-1"));
    }

    private org.springframework.http.HttpStatusCode status(Runnable call) {
        return assertThrows(ResponseStatusException.class, call::run).getStatusCode();
    }
}
