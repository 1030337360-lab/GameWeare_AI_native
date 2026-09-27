package com.gameweare.sandbox;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;

/** HTTP contract required by AgentScope Java's agent-sandbox Kubernetes client. */
public final class SandboxRuntimeServer {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Path DEFAULT_ROOT = Path.of("/workspace");
    private static final int MAX_UPLOAD = 8 * 1024 * 1024;
    private static final int MAX_OUTPUT = 1024 * 1024;

    private final Path root;
    private final Semaphore executions;
    private final long executeTimeoutSeconds;
    private HttpServer server;

    public SandboxRuntimeServer(Path root, int maxConcurrentExecutions, long executeTimeoutSeconds) {
        this.root = root;
        this.executions = new Semaphore(maxConcurrentExecutions);
        this.executeTimeoutSeconds = executeTimeoutSeconds;
    }

    /** Starts the server and returns the bound port; pass 0 for an ephemeral test port. */
    public synchronized int start(int port) throws IOException {
        Files.createDirectories(root);
        server = HttpServer.create(new InetSocketAddress("0.0.0.0", port), 32);
        server.createContext("/", this::handle);
        server.setExecutor(Executors.newFixedThreadPool(8));
        server.start();
        return server.getAddress().getPort();
    }

    public synchronized void stop() {
        if (server != null) server.stop(0);
    }

    public static void main(String[] args) throws IOException {
        new SandboxRuntimeServer(DEFAULT_ROOT, 2, 45).start(8888);
    }

    private void handle(HttpExchange exchange) throws IOException {
        try {
            String route = exchange.getRequestURI().getRawPath();
            String method = exchange.getRequestMethod();
            if (route.equals("/") && method.equals("GET")) { json(exchange, 200, Map.of("ok", true)); return; }
            if (route.equals("/execute") && method.equals("POST")) { execute(exchange); return; }
            if (route.equals("/upload") && method.equals("POST")) { upload(exchange); return; }
            if (route.startsWith("/download/") && method.equals("GET")) { download(exchange, route.substring(10)); return; }
            if (route.startsWith("/list/") && method.equals("GET")) { list(exchange, route.substring(6)); return; }
            if (route.startsWith("/exists/") && method.equals("GET")) { exists(exchange, route.substring(8)); return; }
            json(exchange, 404, Map.of("error", "unknown endpoint"));
        } catch (IllegalArgumentException e) {
            json(exchange, 400, Map.of("error", "invalid request"));
        } catch (Exception e) {
            json(exchange, 500, Map.of("error", "sandbox operation failed"));
        } finally {
            exchange.close();
        }
    }

    private void execute(HttpExchange exchange) throws Exception {
        JsonNode body = JSON.readTree(exchange.getRequestBody().readNBytes(16_385));
        String command = body == null ? "" : body.path("command").asText("");
        if (command.isBlank() || command.length() > 8192) throw new IllegalArgumentException();
        if (!executions.tryAcquire()) { json(exchange, 429, Map.of("error", "busy")); return; }
        try {
            Process process = new ProcessBuilder("sh", "-c", command).directory(root.toFile()).start();
            var executor = Executors.newFixedThreadPool(2);
            try {
                Future<byte[]> out = executor.submit(() -> readLimited(process.getInputStream(), MAX_OUTPUT));
                Future<byte[]> err = executor.submit(() -> readLimited(process.getErrorStream(), MAX_OUTPUT));
                boolean finished = process.waitFor(Duration.ofSeconds(executeTimeoutSeconds).toMillis(), TimeUnit.MILLISECONDS);
                if (!finished) {
                    // Stop the complete command tree before the sandbox accepts another command.
                    List<ProcessHandle> descendants = process.descendants().toList();
                    for (int i = descendants.size() - 1; i >= 0; i--)
                        descendants.get(i).destroyForcibly();
                    process.destroyForcibly();
                    process.waitFor(5, TimeUnit.SECONDS);
                }
                json(exchange, 200, Map.of(
                        "stdout", new String(out.get(5, TimeUnit.SECONDS), StandardCharsets.UTF_8),
                        "stderr", new String(err.get(5, TimeUnit.SECONDS), StandardCharsets.UTF_8),
                        "exit_code", finished ? process.exitValue() : 124));
            } finally { executor.shutdownNow(); }
        } finally { executions.release(); }
    }

    private static byte[] readLimited(java.io.InputStream in, int limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        for (int n; (n = in.read(buffer)) >= 0;) {
            if (out.size() < limit) out.write(buffer, 0, Math.min(n, limit - out.size()));
        }
        return out.toByteArray();
    }

    private void upload(HttpExchange exchange) throws IOException {
        String contentType = exchange.getRequestHeaders().getFirst("Content-Type");
        if (contentType == null || !contentType.startsWith("multipart/form-data; boundary="))
            throw new IllegalArgumentException();
        String boundary = contentType.substring(contentType.indexOf("boundary=") + 9).trim();
        if (boundary.isBlank() || boundary.length() > 100) throw new IllegalArgumentException();
        byte[] body = exchange.getRequestBody().readNBytes(MAX_UPLOAD + 1);
        if (body.length > MAX_UPLOAD) { json(exchange, 413, Map.of("error", "upload too large")); return; }
        String latin = new String(body, StandardCharsets.ISO_8859_1);
        int headerEnd = latin.indexOf("\r\n\r\n");
        int end = latin.lastIndexOf("\r\n--" + boundary + "--");
        if (headerEnd < 0 || end < headerEnd) throw new IllegalArgumentException();
        String headers = latin.substring(0, headerEnd);
        int filenameStart = headers.indexOf("filename=\"");
        if (!headers.contains("name=\"file\"") || filenameStart < 0) throw new IllegalArgumentException();
        filenameStart += 10;
        int filenameEnd = headers.indexOf('"', filenameStart);
        if (filenameEnd < 0) throw new IllegalArgumentException();
        Path target = safePath(headers.substring(filenameStart, filenameEnd), true);
        Files.createDirectories(target.getParent());
        Files.write(target, java.util.Arrays.copyOfRange(body, headerEnd + 4, end),
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        json(exchange, 200, Map.of("ok", true));
    }

    private void download(HttpExchange exchange, String encoded) throws IOException {
        Path path = safePath(URLDecoder.decode(encoded, StandardCharsets.UTF_8), false);
        if (!Files.isRegularFile(path)) { json(exchange, 404, Map.of("error", "missing file")); return; }
        long size = Files.size(path);
        if (size > MAX_UPLOAD) { json(exchange, 413, Map.of("error", "file too large")); return; }
        byte[] content = Files.readAllBytes(path);
        exchange.getResponseHeaders().set("Content-Type", "application/octet-stream");
        exchange.sendResponseHeaders(200, content.length);
        exchange.getResponseBody().write(content);
    }

    private void list(HttpExchange exchange, String encoded) throws IOException {
        Path path = safePath(URLDecoder.decode(encoded, StandardCharsets.UTF_8), false);
        if (!Files.isDirectory(path)) { json(exchange, 200, List.of()); return; }
        List<Map<String, Object>> entries = new ArrayList<>();
        try (var stream = Files.list(path)) {
            for (Path child : stream.sorted(Comparator.comparing(Path::toString)).limit(1000).toList()) {
                entries.add(Map.of("name", child.getFileName().toString(),
                        "size", Files.isRegularFile(child) ? Files.size(child) : 0L,
                        "type", Files.isDirectory(child) ? "directory" : "file",
                        "mod_time", Files.getLastModifiedTime(child).toMillis() / 1000.0));
            }
        }
        json(exchange, 200, entries);
    }

    private void exists(HttpExchange exchange, String encoded) throws IOException {
        Path path = safePath(URLDecoder.decode(encoded, StandardCharsets.UTF_8), false);
        json(exchange, 200, Map.of("exists", Files.exists(path)));
    }

    private Path safePath(String raw, boolean writing) throws IOException {
        if (raw == null || raw.isBlank() || raw.indexOf('\0') >= 0 || raw.indexOf('\\') >= 0)
            throw new IllegalArgumentException();
        Path path = Path.of(raw);
        Path resolved = (path.isAbsolute() ? path : root.resolve(path)).normalize();
        if (!resolved.startsWith(root)) throw new IllegalArgumentException();
        Path ancestor = writing ? resolved.getParent() : resolved;
        while (ancestor != null && !Files.exists(ancestor)) ancestor = ancestor.getParent();
        if (ancestor != null && !ancestor.toRealPath().startsWith(root.toRealPath()))
            throw new IllegalArgumentException();
        if (writing && Files.exists(resolved, java.nio.file.LinkOption.NOFOLLOW_LINKS)
                && !resolved.toRealPath().startsWith(root.toRealPath()))
            throw new IllegalArgumentException();
        return resolved;
    }

    private static void json(HttpExchange exchange, int status, Object body) throws IOException {
        byte[] content = JSON.writeValueAsBytes(body);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, content.length);
        exchange.getResponseBody().write(content);
    }
}
