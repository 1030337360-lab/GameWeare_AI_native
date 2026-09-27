package com.gameweare.api.create;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.harness.agent.filesystem.AbstractFilesystem;
import io.agentscope.harness.agent.filesystem.model.FileDownloadResponse;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.Test;

class GameValidationToolTest {
    private static final String GOOD = "<!doctype html><html><head><title>Game</title></head>"
            + "<body><canvas></canvas><script>let score = 0;</script></body></html>";

    @Test void requiresPassingValidationOfTheExactDeliveredBytes() {
        AbstractFilesystem filesystem = mock(AbstractFilesystem.class);
        GameValidationTool tool = new GameValidationTool("job-1", new ArtifactValidator());
        RuntimeContext context = RuntimeContext.builder().sessionId("job-1")
                .put(AbstractFilesystem.class, filesystem).build();
        byte[] good = GOOD.getBytes(StandardCharsets.UTF_8);
        when(filesystem.downloadFiles(any(), anyList()))
                .thenReturn(List.of(FileDownloadResponse.success("index.html", good)));

        assertFalse(tool.matchesValidatedContent(good));
        assertTrue(tool.validateGameHtml(context, "index.html").startsWith("PASS:"));
        assertTrue(tool.matchesValidatedContent(good));
        assertFalse(tool.matchesValidatedContent((GOOD + " ").getBytes(StandardCharsets.UTF_8)));

        byte[] invalid = GOOD.replace("let score = 0", "let score = ;")
                .getBytes(StandardCharsets.UTF_8);
        when(filesystem.downloadFiles(any(), anyList()))
                .thenReturn(List.of(FileDownloadResponse.success("index.html", invalid)));
        String failure = tool.validateGameHtml(context, "index.html");
        assertTrue(failure.contains("JS_SYNTAX"));
        assertTrue(failure.contains("script #1"));
        assertTrue(failure.contains("line 1"));
        assertTrue(tool.lastFailure().contains("JS_SYNTAX"));
        assertFalse(tool.matchesValidatedContent(good));
    }

    @Test void rejectsOtherJobsAndPaths() {
        GameValidationTool tool = new GameValidationTool("job-1", new ArtifactValidator());
        RuntimeContext other = RuntimeContext.builder().sessionId("job-2").build();
        assertTrue(tool.validateGameHtml(other, "index.html").startsWith("FAIL:"));
        RuntimeContext right = RuntimeContext.builder().sessionId("job-1").build();
        assertTrue(tool.validateGameHtml(right, "../index.html").startsWith("FAIL:"));
    }
}
