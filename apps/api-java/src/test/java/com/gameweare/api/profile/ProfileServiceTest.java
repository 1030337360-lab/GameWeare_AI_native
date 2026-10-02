package com.gameweare.api.profile;

import com.gameweare.api.profile.dao.ProfileMapper;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ProfileServiceTest {
    @Test
    void anotherUsersProjectIsNotReturned() {
        ProfileMapper mapper = mock(ProfileMapper.class);
        when(mapper.project("project-id", "caller-id")).thenReturn(null);

        ResponseStatusException error = assertThrows(ResponseStatusException.class,
                () -> new ProfileService(mapper).project("caller-id", "project-id"));

        assertEquals(HttpStatus.NOT_FOUND, error.getStatusCode());
    }
}
