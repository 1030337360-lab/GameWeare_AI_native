package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;

import org.junit.jupiter.api.Test;

class LlmEndpointPolicyTest {
    @Test
    void exactHostAllowlistAndHttpsAreRequired() {
        var policy = new LlmEndpointPolicy("api.example.com,api.other.com", false);
        assertDoesNotThrow(() -> policy.validate(URI.create("https://api.example.com/v1")));
        assertThrows(IllegalArgumentException.class, () -> policy.validate(URI.create("https://evil.api.example.com/v1")));
        assertThrows(IllegalArgumentException.class, () -> policy.validate(URI.create("http://api.example.com/v1")));
        assertThrows(IllegalArgumentException.class, () -> policy.validate(URI.create("https://api.example.com/v1?next=http://localhost")));
        assertThrows(IllegalArgumentException.class, () -> policy.validate(URI.create("https://user:secret@api.example.com/v1")));
    }

    @Test
    void privateAndSpecialUseAddressesAreRejected() throws Exception {
        for (String ip : new String[] {"127.0.0.1", "10.1.2.3", "169.254.169.254", "100.64.0.1",
                "192.0.0.1", "198.18.0.1", "0.0.0.0", "::1", "fc00::1", "2001:db8::1"})
            org.junit.jupiter.api.Assertions.assertFalse(LlmEndpointPolicy.isPublicAddress(InetAddress.getByName(ip)), ip);
        org.junit.jupiter.api.Assertions.assertTrue(LlmEndpointPolicy.isPublicAddress(InetAddress.getByName("8.8.8.8")));
        assertThrows(UnknownHostException.class, () -> new LlmEndpointPolicy("", false).resolve("localhost"));
        assertDoesNotThrow(() -> new LlmEndpointPolicy("", true).resolve("localhost"));
    }
}
