package com.gameweare.api.create;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class CreateWorkerTest {
    @Test void titleIsBounded() {
        assertEquals(80, CreateService.title("x".repeat(120)).length());
    }
}
