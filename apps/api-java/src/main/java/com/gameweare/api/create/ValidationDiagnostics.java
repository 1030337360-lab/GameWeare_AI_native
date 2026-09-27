package com.gameweare.api.create;

import java.util.List;

/** Human-readable diagnostics shared by the agent tool and persisted job failures. */
final class ValidationDiagnostics {
    private ValidationDiagnostics() {}

    static String format(List<ArtifactValidator.Diagnostic> diagnostics) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < diagnostics.size(); i++) {
            ArtifactValidator.Diagnostic diagnostic = diagnostics.get(i);
            if (i > 0) result.append('\n');
            result.append(i + 1).append(". [").append(diagnostic.code()).append("] ");
            if (diagnostic.scriptIndex() > 0) {
                result.append("script #").append(diagnostic.scriptIndex());
                if (diagnostic.line() > 0) result.append(", line ").append(diagnostic.line());
                result.append(": ");
            }
            result.append(diagnostic.message());
        }
        return result.toString();
    }
}
