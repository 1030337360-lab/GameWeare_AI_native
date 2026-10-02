package com.gameweare.api.play;

import io.minio.GetObjectArgs;
import io.minio.MinioClient;
import com.gameweare.api.catalog.GameTrendingService;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.net.URI;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class PlayController {
    private final PlayService play;

    public PlayController(PlayService play) { this.play = play; }

    @GetMapping("/play/{id}/manifest")
    public Map<String, Object> manifest(@PathVariable String id) { return play.manifest(id); }

    @GetMapping("/play/{id}/document")
    public ResponseEntity<byte[]> document(@PathVariable String id) { return play.document(id); }

    @PostMapping({"/events/play", "/play/events"})
    public Map<String, Object> event(@RequestBody PlayEvent event, HttpServletRequest request) {
        Object userId = request.getAttribute("userId");
        return play.event(event, userId == null ? null : userId.toString());
    }

    public record PlayEvent(String gameId, String event, String anonymousId, Instant occurredAt,
                            Long durationMs, String errorMessage, Map<String, Object> metadata) {}
}
