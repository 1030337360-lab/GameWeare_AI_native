package com.gameweare.api.create;

import com.gameweare.api.billing.TokenBillingService;
import io.minio.MinioClient;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class CreateTaskCancellationTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final TokenBillingService billing = mock(TokenBillingService.class);
    private final CreateService service = new CreateService(db, billing, mock(MinioClient.class),
            "test-secret-that-is-32-chars-long", "bucket");

    @Test
    void anotherUserCannotCancelTask() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("job"), eq("other")))
                .thenThrow(new EmptyResultDataAccessException(1));
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.cancelJob("other", "job"));
        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
        verifyNoInteractions(billing);
    }

    @Test
    void runningTaskIsCanceledAndReservationRefunded() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("job"), eq("owner")))
                .thenReturn(Map.of("status", "generating", "project_id", "project"));
        when(db.queryForObject(contains("MAX(step_no)"), eq(Integer.class), eq("job"))).thenReturn(4);
        Map<String, Object> result = service.cancelJob("owner", "job");
        assertEquals("canceled", result.get("status"));
        verify(db).update(contains("status='canceled'"), eq("job"));
        verify(billing).refund("owner", "job");
    }

    @Test
    void completedTaskCannotBeCanceled() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("job"), eq("owner")))
                .thenReturn(Map.of("status", "completed", "project_id", "project"));
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.cancelJob("owner", "job"));
        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
        verifyNoInteractions(billing);
    }
}
