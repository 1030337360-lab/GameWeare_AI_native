package com.gameweare.api.play;

import com.gameweare.api.play.dao.PlayMapper;
import io.minio.MinioClient;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** The unique MySQL dedupe row remains authoritative after moving SQL to MyBatis. */
class PlayServiceTest {
    private final PlayMapper mapper = mock(PlayMapper.class);
    private final PlayService service = new PlayService(mapper, mock(MinioClient.class), "bucket", "http://localhost:1314");

    private PlayController.PlayEvent event(String type, String anonymousId) {
        return new PlayController.PlayEvent("game-slug", type, anonymousId, Instant.now(), null, null, Map.of());
    }

    @Test void invalidEventTypeIsRejected() {
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.event(event("cheat", null), "u1")));
    }

    @Test void unknownGameIsRejected() {
        when(mapper.publicGameId("game-slug")).thenReturn(null);
        assertEquals(HttpStatus.NOT_FOUND, status(() -> service.event(event("game_start", null), "u1")));
    }

    @Test void firstStartInWindowCountsThePlay() {
        publishedGame();
        when(mapper.countOnce(eq("game-1"), eq("u:u1"), any(Timestamp.class))).thenReturn(1);
        Map<String, Object> out = service.event(event("game_start", null), "u1");
        assertTrue((Boolean) out.get("counted"));
        verify(mapper).incrementPlays("game-1");
        verify(mapper).insertEvent(anyString(), eq("u1"), eq(null), eq("game-1"), eq("game_start"));
    }

    @Test void duplicateStartInWindowIsNotCountedAgain() {
        publishedGame();
        Map<String, Object> out = service.event(event("game_view", null), "u1");
        assertFalse((Boolean) out.get("counted"));
        verify(mapper, never()).incrementPlays("game-1");
    }

    @Test void anonymousIdentityUsesAnonymousPrefix() {
        publishedGame();
        when(mapper.countOnce(eq("game-1"), eq("a:anon-42"), any(Timestamp.class))).thenReturn(1);
        assertTrue((Boolean) service.event(event("game_start", "anon-42"), null).get("counted"));
        verify(mapper).insertEvent(anyString(), eq(null), eq("anon-42"), eq("game-1"), eq("game_start"));
    }

    @Test void loggedInUserOverridesAnonymousIdentity() {
        publishedGame();
        service.event(event("game_start", "anon-42"), "u1");
        verify(mapper).insertEvent(anyString(), eq("u1"), eq(null), eq("game-1"), eq("game_start"));
    }

    @Test void eventsWithoutIdentityAreStoredButNotCounted() {
        publishedGame();
        assertFalse((Boolean) service.event(event("game_load_error", null), null).get("counted"));
        verify(mapper, never()).countOnce(anyString(), anyString(), any(Timestamp.class));
        verify(mapper, never()).incrementPlays("game-1");
    }

    @Test void oversizedAnonymousIdIsRejected() {
        publishedGame();
        assertEquals(HttpStatus.BAD_REQUEST, status(() -> service.event(event("game_start", "x".repeat(65)), null)));
    }

    private void publishedGame() { when(mapper.publicGameId("game-slug")).thenReturn("game-1"); }
    private org.springframework.http.HttpStatusCode status(Runnable call) {
        return assertThrows(ResponseStatusException.class, call::run).getStatusCode();
    }
}
