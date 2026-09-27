package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class CreateFailureDetailsTest {
    @Test void reportsStageAndNestedCauseInsteadOfGenericMessage() {
        Exception failure = new IllegalStateException("Agent failed validation: [JS_SYNTAX] script #1, line 8: unexpected token",
                new java.net.SocketTimeoutException("Read timed out after 180 seconds"));
        String details = CreateFailureDetails.describe("AI generation", failure);
        assertTrue(details.contains("Failed at AI generation"));
        assertTrue(details.contains("JS_SYNTAX"));
        assertTrue(details.contains("line 8"));
        assertTrue(details.contains("SocketTimeoutException"));
        assertTrue(details.contains("180 seconds"));
    }

    @Test void redactsCredentialsButKeepsTheError() {
        String details = CreateFailureDetails.describe("AI generation", new IllegalStateException(
                "HTTP 401 Authorization: Bearer sk-super-secret-value; api_key=sk-another-secret-value"));
        assertTrue(details.contains("HTTP 401"));
        assertFalse(details.contains("sk-super-secret-value"));
        assertFalse(details.contains("sk-another-secret-value"));
    }
}
