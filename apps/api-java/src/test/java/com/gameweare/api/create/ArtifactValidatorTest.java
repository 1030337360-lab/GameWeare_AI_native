package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ArtifactValidatorTest {
    private final ArtifactValidator validator = new ArtifactValidator();

    @Test void validatesSyntaxWithoutRunningGeneratedCode() {
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas id='game'></canvas>"
                + "<script>throw new Error('must never run'); const game = () => 1;</script></body></html>";
        ArtifactValidator.Result result = validator.validate(html);
        assertTrue(result.ok(), () -> result.diagnostics().toString());
        assertEquals(html, result.normalizedHtml());
    }

    @Test void removesModelCommentaryAroundHtmlDocument() {
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script>const ready = true;</script></body></html>";
        ArtifactValidator.Result result = validator.validate("Here is your game.\n```html\n" + html
                + "\n```\nSome playing instructions.");
        assertTrue(result.ok(), () -> result.diagnostics().toString());
        assertEquals(html, result.normalizedHtml());
    }

    @Test void returnsScriptLocationForSyntaxError() {
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas id='game'></canvas>"
                + "<script>const score = ;</script></body></html>";
        ArtifactValidator.Result result = validator.validate(html);
        assertFalse(result.ok());
        assertEquals("JS_SYNTAX", result.diagnostics().get(0).code());
        assertEquals(1, result.diagnostics().get(0).scriptIndex());
        assertTrue(result.diagnostics().get(0).line() > 0);
    }

    @Test void refusesExternalResources() {
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script src='https://example.com/remote.js'></script><script>const x = 1;</script></body></html>";
        assertFalse(validator.validate(html).ok());
    }

    @Test void reportsRemoteUrlInInlineCodeButIgnoresExplanatoryTextOutsideDocument() {
        String html = "<!doctype html><html><head><title>Game</title></head><body><canvas></canvas>"
                + "<script>fetch('https://invalid.example/data');</script></body></html>";
        ArtifactValidator.Result failed = validator.validate(html);
        assertFalse(failed.ok());
        assertTrue(failed.diagnostics().stream().anyMatch(d -> d.code().equals("EXTERNAL_HTTP_RESOURCE")
                && d.message().contains("invalid.example")));
        String clean = html.replace("fetch('https://invalid.example/data');", "const ready = true;");
        assertTrue(validator.validate("See https://docs.example/help\n" + clean + "\nDone.").ok());
    }

    @Test void refusesAHiddenStartButtonAndHiddenGame() {
        String html = "<!doctype html><html><head><style>#game,#start{display:none}</style></head>"
                + "<body><div id='start'><button id='go'>Start</button></div><div id='game'>Play</div>"
                + "<script>document.getElementById('go').onclick = function(){"
                + "document.getElementById('game').style.display='block';};</script></body></html>";
        ArtifactValidator.Result failed = validator.validate(html);
        assertFalse(failed.ok());
        assertTrue(failed.diagnostics().stream().anyMatch(d -> d.code().equals("START_SCREEN_HIDDEN")));
        assertFalse(validator.validate(html.replace("id='start'", "id='start' style='color:red'")).ok());
        assertTrue(validator.validate(html.replace("#game,#start{display:none}", "#game{display:none}")).ok());
    }
}
