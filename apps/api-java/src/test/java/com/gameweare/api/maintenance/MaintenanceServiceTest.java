package com.gameweare.api.maintenance;

import com.gameweare.api.create.CreateService;
import io.minio.MinioClient;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class MaintenanceServiceTest {
    @Test
    void normalUserCannotReadMaintenanceJobs() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), eq(String.class), eq("user-id"))).thenReturn(List.of("user"));
        MaintenanceService service = new MaintenanceService(jdbc, mock(MinioClient.class), mock(CreateService.class));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.jobs("user-id", null, 50));

        assertEquals(HttpStatus.FORBIDDEN, error.getStatusCode());
    }

    @Test
    void maintainerCannotSetInvalidVisibility() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), eq(String.class), eq("maintainer-id"))).thenReturn(List.of("maintainer"));
        MaintenanceService service = new MaintenanceService(jdbc, mock(MinioClient.class), mock(CreateService.class));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.updateGame("maintainer-id", "game-1", java.util.Map.of("visibility", "everyone")));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
    }

    @Test
    void maintainerCannotSetInvalidPublishStatus() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForList(anyString(), eq(String.class), eq("maintainer-id"))).thenReturn(List.of("admin"));
        MaintenanceService service = new MaintenanceService(jdbc, mock(MinioClient.class), mock(CreateService.class));

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> service.updateGame("maintainer-id", "game-1", java.util.Map.of("publishStatus", "viral")));

        assertEquals(HttpStatus.BAD_REQUEST, error.getStatusCode());
    }
}
