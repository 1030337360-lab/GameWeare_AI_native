package com.gameweare.api.create;

import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.tool.Tool;
import io.agentscope.core.tool.ToolParam;
import io.agentscope.harness.agent.filesystem.AbstractFilesystem;
import io.agentscope.harness.agent.filesystem.model.FileDownloadResponse;
import io.agentscope.harness.agent.workspace.WorkspacePathNormalizer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/** Returns actionable SVG parse errors to the cover ReAct agent. */
final class CoverValidationTool {
    private final String sessionId;
    private final AtomicReference<String> validatedSha256 = new AtomicReference<>();
    private final AtomicReference<byte[]> safeSvg = new AtomicReference<>();
    private final AtomicReference<String> lastFailure = new AtomicReference<>();

    CoverValidationTool(String sessionId) { this.sessionId = sessionId; }

    @Tool(name = "validate_cover_svg", description = "Parse and security-check this job's cover.svg in the "
            + "sandbox. On FAIL, repair the listed SVG error and call this tool again. A PASS for the "
            + "unchanged file is required before deliver_artifact.", readOnly = true)
    public String validateCoverSvg(RuntimeContext context,
            @ToolParam(name = "filePath", description = "Must be cover.svg") String filePath) {
        validatedSha256.set(null);
        safeSvg.set(null);
        if (context == null || !sessionId.equals(context.getSessionId()))
            return fail("FAIL: Cover validation session does not match this job.");
        if (!"cover.svg".equals(filePath))
            return fail("FAIL: filePath must be exactly cover.svg.");
        AbstractFilesystem filesystem = context.get(AbstractFilesystem.class);
        if (filesystem == null) return fail("FAIL: Cover sandbox filesystem is unavailable.");
        WorkspacePathNormalizer normalizer = context.get(WorkspacePathNormalizer.class);
        String path = normalizer == null ? filePath : normalizer.normalize(filePath);
        List<FileDownloadResponse> files;
        try {
            files = filesystem.downloadFiles(context, List.of(path));
        } catch (Exception error) {
            return fail("FAIL: Could not read cover.svg from the sandbox: " + error.getMessage());
        }
        if (files.isEmpty() || !files.get(0).isSuccess())
            return fail("FAIL: cover.svg does not exist or could not be read; write the file first.");
        byte[] bytes = files.get(0).content();
        if (bytes == null || bytes.length == 0) return fail("FAIL: cover.svg is empty.");
        if (bytes.length > 100_000)
            return fail("FAIL: cover.svg is " + bytes.length + " bytes; maximum is 100,000 bytes.");
        try {
            byte[] normalized = CoverGenerator.safeSvg(new String(bytes, StandardCharsets.UTF_8));
            validatedSha256.set(sha256(bytes));
            safeSvg.set(normalized);
            lastFailure.set(null);
            return "PASS: cover.svg is valid static SVG; now call deliver_artifact.";
        } catch (Exception error) {
            return fail("FAIL: SVG parse or safety check failed (" + error.getClass().getSimpleName()
                    + "): " + error.getMessage());
        }
    }

    boolean matchesValidatedContent(byte[] bytes) {
        String expected = validatedSha256.get();
        return expected != null && bytes != null && expected.equals(sha256(bytes));
    }

    byte[] safeSvg() { return safeSvg.get(); }
    String lastFailure() { return lastFailure.get(); }

    private String fail(String message) {
        lastFailure.set(message);
        return message;
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 is unavailable", error);
        }
    }
}
