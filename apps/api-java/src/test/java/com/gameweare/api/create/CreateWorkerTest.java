package com.gameweare.api.create;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class CreateWorkerTest {
    @Test void acceptsSelfContainedHtml() {
        String html = "<!doctype html><html><head><title>Test</title></head><body><canvas></canvas><script>const game = true;</script></body></html>";
        assertEquals(html, CreateWorker.validateHtml("```html\n" + html + "\n```"));
    }

    @Test void rejectsExternalScriptsAndNonHtml() {
        assertThrows(IllegalStateException.class, () -> CreateWorker.validateHtml("No game"));
        assertThrows(IllegalStateException.class, () -> CreateWorker.validateHtml("<html><body><script src=\"https://evil.example/a.js\"></script></body></html>"));
    }

    @Test void titleIsBounded() {
        assertEquals(80, CreateService.title("x".repeat(120)).length());
    }
}
