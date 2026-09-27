package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class CoverGeneratorTest {
    @Test
    void acceptsStaticSvgAndNormalizesSize() throws Exception {
        String source = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='1200' height='900' fill='#123456'/>"
                + "<text x='20' y='50'>Arcade</text></svg>";
        String sanitized = new String(CoverGenerator.safeSvg(source), StandardCharsets.UTF_8);
        assertTrue(sanitized.contains("width=\"1200\""));
        assertTrue(sanitized.contains("Arcade"));
    }

    @Test
    void rejectsScriptAndExternalReferences() {
        assertThrows(IllegalArgumentException.class, () -> CoverGenerator.safeSvg(
                "<svg><script>alert(1)</script></svg>"));
        assertThrows(IllegalArgumentException.class, () -> CoverGenerator.safeSvg(
                "<svg><rect fill='url(https://example.com/x)'/></svg>"));
        assertThrows(Exception.class, () -> CoverGenerator.safeSvg(
                "<!DOCTYPE svg [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><svg>&x;</svg>"));
    }

    @Test
    void fallbackEscapesUserTitle() {
        String svg = new String(CoverGenerator.fallback("<script>&", "game"), StandardCharsets.UTF_8);
        assertFalse(svg.contains("<script>"));
        assertTrue(svg.contains("&lt;script&gt;&amp;"));
    }
}
