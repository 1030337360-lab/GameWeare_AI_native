package com.gameweare.api.create;

import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Set;
import java.util.regex.Pattern;

/** Gives creators the actual failed stage and exception chain without publishing credentials. */
final class CreateFailureDetails {
    private static final Pattern BEARER = Pattern.compile("(?i)Bearer\\s+[^\\s\\\"',}]+", Pattern.CASE_INSENSITIVE);
    private static final Pattern CREDENTIAL = Pattern.compile(
            "(?i)(api[_-]?key|authorization|access[_-]?key|secret|password|token)\\s*[=:]\\s*[^\\s,;}]+", Pattern.CASE_INSENSITIVE);
    private static final Pattern LOCAL_GATEWAY = Pattern.compile("/internal/agent-model/[^/\\s]+/v1");
    private static final Pattern PROVIDER_KEY = Pattern.compile("\\bsk-[A-Za-z0-9_-]{8,}\\b");

    private CreateFailureDetails() {}

    static String describe(String stage, Throwable error) {
        StringBuilder out = new StringBuilder("Failed at ").append(stage).append(':');
        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        Throwable current = error;
        int depth = 0;
        while (current != null && depth < 5 && seen.add(current)) {
            String message = current.getMessage();
            out.append('\n').append(depth == 0 ? "Error" : "Caused by")
                    .append(" (").append(current.getClass().getSimpleName()).append("): ")
                    .append(message == null || message.isBlank() ? "No exception message was provided"
                            : redact(message));
            current = current.getCause();
            depth++;
        }
        if (current != null) out.append("\nAdditional nested causes are available in server logs.");
        String result = out.toString();
        return result.length() > 3500 ? result.substring(0, 3500) + "\nDetails truncated; see server logs." : result;
    }

    private static String redact(String text) {
        String clean = BEARER.matcher(text).replaceAll("Bearer [redacted]");
        clean = CREDENTIAL.matcher(clean).replaceAll("$1=[redacted]");
        clean = LOCAL_GATEWAY.matcher(clean).replaceAll("/internal/agent-model/[redacted]/v1");
        return PROVIDER_KEY.matcher(clean).replaceAll("[redacted]");
    }
}
