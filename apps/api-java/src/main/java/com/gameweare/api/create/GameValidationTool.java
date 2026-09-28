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

/** Validates the exact sandbox file that the agent will deliver. */
final class GameValidationTool {
    record CandidateResult(boolean passed, String normalizedHtml, String feedback) {}
    private final String jobId;
    private final ArtifactValidator validator;
    private final AtomicReference<String> validatedSha256 = new AtomicReference<>();
    private final AtomicReference<String> lastFailure = new AtomicReference<>();

    GameValidationTool(String jobId, ArtifactValidator validator) {
        this.jobId = jobId;
        this.validator = validator;
    }

    @Tool(name = "validate_game_html", description = "Validate the current index.html in this job's sandbox. "
            + "Checks HTML packaging and JavaScript syntax without running generated code. "
            + "Fix any reported error and call this tool again. A PASS for the latest file is required "
            + "before deliver_artifact; changing the file invalidates the PASS.", readOnly = true)
    public String validateGameHtml(RuntimeContext context,
            @ToolParam(name = "filePath", description = "The game file; must be index.html") String filePath) {
        validatedSha256.set(null);
        if (context == null || !jobId.equals(context.getSessionId()))
            return fail("FAIL: Validation session does not match the current job; retry in this job's sandbox.");
        if (!"index.html".equals(filePath))
            return fail("FAIL: filePath must be exactly index.html; received " + filePath);
        AbstractFilesystem filesystem = context.get(AbstractFilesystem.class);
        if (filesystem == null) return fail("FAIL: Sandbox filesystem is unavailable for this job.");
        WorkspacePathNormalizer normalizer = context.get(WorkspacePathNormalizer.class);
        String path = normalizer == null ? filePath : normalizer.normalize(filePath);
        List<FileDownloadResponse> files = filesystem.downloadFiles(context, List.of(path));
        if (files.isEmpty() || !files.get(0).isSuccess())
            return fail("FAIL: index.html could not be read from the sandbox; write the file before validation.");
        byte[] content = files.get(0).content();
        if (content == null) return fail("FAIL: Sandbox returned no bytes for index.html.");
        if (content.length > 2_000_000)
            return fail("FAIL: index.html is " + content.length + " bytes; maximum is 2,000,000 bytes.");
        CandidateResult result = validateCandidate(new String(content, StandardCharsets.UTF_8));
        if (!result.passed()) return fail(result.feedback());
        validatedSha256.set(sha256(content));
        lastFailure.set(null);
        return result.feedback() + " Now call deliver_artifact.";
    }

    CandidateResult validateCandidate(String html) {
        ArtifactValidator.Result result = validator.validate(html);
        if (!result.ok()) return new CandidateResult(false, "",
                "FAIL: index.html has " + result.diagnostics().size() + " validation error(s):\n"
                        + ValidationDiagnostics.format(result.diagnostics())
                        + "\nFix every error and call validate_game_html again with the complete revised HTML.");
        return new CandidateResult(true, result.normalizedHtml(),
                "PASS: index.html passed HTML, external resource and JavaScript syntax validation.");
    }

    String lastFailure() { return lastFailure.get(); }

    private String fail(String message) {
        lastFailure.set(message);
        return message;
    }

    boolean matchesValidatedContent(byte[] content) {
        String expected = validatedSha256.get();
        return expected != null && content != null && expected.equals(sha256(content));
    }

    private static String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }
}
