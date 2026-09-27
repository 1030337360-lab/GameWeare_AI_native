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

class CoverValidationToolTest {
    @Test void sendsSpecificErrorsAndRequiresRevalidationOfExactBytes() {
        AbstractFilesystem filesystem = mock(AbstractFilesystem.class);
        CoverValidationTool tool = new CoverValidationTool("job-1-cover");
        RuntimeContext context = RuntimeContext.builder().sessionId("job-1-cover")
                .put(AbstractFilesystem.class, filesystem).build();
        byte[] invalid = "<svg><script>alert(1)</script></svg>".getBytes(StandardCharsets.UTF_8);
        byte[] valid = "<svg xmlns='http://www.w3.org/2000/svg'><rect width='1200' height='900' fill='#123456'/></svg>"
                .getBytes(StandardCharsets.UTF_8);
        when(filesystem.downloadFiles(any(), anyList()))
                .thenReturn(List.of(FileDownloadResponse.success("cover.svg", invalid)))
                .thenReturn(List.of(FileDownloadResponse.success("cover.svg", valid)));

        assertFalse(tool.matchesValidatedContent(valid));
        String failure = tool.validateCoverSvg(context, "cover.svg");
        assertTrue(failure.contains("Unsupported SVG element"), failure);
        assertFalse(tool.matchesValidatedContent(invalid));
        assertTrue(tool.validateCoverSvg(context, "cover.svg").startsWith("PASS:"));
        assertTrue(tool.matchesValidatedContent(valid));
        assertFalse(tool.matchesValidatedContent((new String(valid, StandardCharsets.UTF_8) + " ")
                .getBytes(StandardCharsets.UTF_8)));
        assertTrue(new String(tool.safeSvg(), StandardCharsets.UTF_8).contains("viewBox=\"0 0 1200 900\""));
    }

    @Test void rejectsOtherSessionsAndPaths() {
        CoverValidationTool tool = new CoverValidationTool("job-1-cover");
        assertTrue(tool.validateCoverSvg(RuntimeContext.builder().sessionId("job-2-cover").build(),
                "cover.svg").contains("session"));
        assertTrue(tool.validateCoverSvg(RuntimeContext.builder().sessionId("job-1-cover").build(),
                "../cover.svg").contains("exactly cover.svg"));
    }
}
