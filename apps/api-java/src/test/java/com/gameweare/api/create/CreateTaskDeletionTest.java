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
import static org.mockito.Mockito.verifyNoMoreInteractions;
import static org.mockito.Mockito.when;

class CreateTaskDeletionTest {
    private final JdbcTemplate db = mock(JdbcTemplate.class);
    private final CreateService service = new CreateService(db, mock(TokenBillingService.class),
            mock(MinioClient.class), "test-secret-that-is-32-chars-long", "bucket");

    @Test
    void anotherUsersTaskCannotBeDeleted() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("task-1"), eq("user-2")))
                .thenThrow(new EmptyResultDataAccessException(1));
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.deleteJob("user-2", "task-1"));
        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
        verify(db).queryForMap(contains("FOR UPDATE"), eq("task-1"), eq("user-2"));
        verifyNoMoreInteractions(db);
    }

    @Test
    void runningTaskCannotBeDeleted() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("task-1"), eq("user-1")))
                .thenReturn(Map.of("status", "generating", "project_id", "project-1"));
        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.deleteJob("user-1", "task-1"));
        assertEquals(HttpStatus.CONFLICT, error.getStatusCode());
    }

    @Test
    void finishedTaskIsHiddenWithoutDeletingItsGameOrLedger() {
        when(db.queryForMap(contains("FOR UPDATE"), eq("task-1"), eq("user-1")))
                .thenReturn(Map.of("status", "completed", "project_id", "project-1"));
        when(db.queryForObject(contains("COUNT(*) FROM create_jobs"), eq(Integer.class), eq("project-1")))
                .thenReturn(0);
        service.deleteJob("user-1", "task-1");
        verify(db).update(contains("SET deleted_at=NOW(6)"), eq("task-1"), eq("user-1"));
    }
}
