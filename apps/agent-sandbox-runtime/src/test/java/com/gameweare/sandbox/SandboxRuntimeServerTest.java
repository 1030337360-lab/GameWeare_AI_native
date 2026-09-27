package com.gameweare.sandbox;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledOnOs;
import org.junit.jupiter.api.condition.OS;
import org.junit.jupiter.api.io.TempDir;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * HTTP contract and hardening tests for the sandbox runtime. Path safety, upload,
 * download, list and exists run everywhere; shell-dependent behaviour (execute, timeout,
 * concurrency) only runs where /bin/sh exists.
 */
class SandboxRuntimeServerTest {
    @TempDir
    Path root;

    private final HttpClient http = HttpClient.newHttpClient();
    private SandboxRuntimeServer server;
    private String base;

    private void start(long executeTimeoutSeconds) throws IOException {
        server = new SandboxRuntimeServer(root, 1, executeTimeoutSeconds);
        int port = server.start(0);
        base = "http://127.0.0.1:" + port;
    }

    @AfterEach
    void tearDown() {
        if (server != null) server.stop();
    }

    private HttpResponse<String> get(String path) throws Exception {
        return http.send(HttpRequest.newBuilder(URI.create(base + path)).GET().build(),
                HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> post(String path, String contentType, byte[] body) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create(base + path))
                .POST(HttpRequest.BodyPublishers.ofByteArray(body));
        if (contentType != null) builder.header("Content-Type", contentType);
        return http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }

    private static byte[] multipart(String boundary, String filename, byte[] content) {
        var out = new ByteArrayOutputStream();
        String head = "--" + boundary + "\r\n"
                + "Content-Disposition: form-data; name=\"file\"; filename=\"" + filename + "\"\r\n\r\n";
        out.writeBytes(head.getBytes(StandardCharsets.ISO_8859_1));
        out.writeBytes(content);
        out.writeBytes(("\r\n--" + boundary + "--\r\n").getBytes(StandardCharsets.ISO_8859_1));
        return out.toByteArray();
    }

    @Test
    void healthEndpointReportsOk() throws Exception {
        start(1);
        HttpResponse<String> response = get("/");
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"ok\":true"));
    }

    @Test
    void uploadThenDownloadRoundTripsFileContent() throws Exception {
        start(1);
        byte[] content = "<html><body>sandbox</body></html>".getBytes(StandardCharsets.UTF_8);
        HttpResponse<String> uploaded = post("/upload",
                "multipart/form-data; boundary=testboundary", multipart("testboundary", "index.html", content));
        assertEquals(200, uploaded.statusCode());
        assertEquals(content, Files.readAllBytes(root.resolve("index.html")));

        HttpResponse<byte[]> downloaded = http.send(
                HttpRequest.newBuilder(URI.create(base + "/download/index.html")).GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertEquals(200, downloaded.statusCode());
        assertEquals(new String(content, StandardCharsets.UTF_8), new String(downloaded.body(), StandardCharsets.UTF_8));
    }

    @Test
    void uploadRejectsPathTraversalFilenames() throws Exception {
        start(1);
        HttpResponse<String> response = post("/upload",
                "multipart/form-data; boundary=testboundary",
                multipart("testboundary", "../escape.html", "x".getBytes(StandardCharsets.UTF_8)));
        assertEquals(400, response.statusCode());
        assertTrue(Stream.of(root.toFile().list()).noneMatch(name -> name.contains("escape")));
    }

    @Test
    void uploadRejectsBackslashAndAbsoluteFilenames() throws Exception {
        start(1);
        assertEquals(400, post("/upload", "multipart/form-data; boundary=b",
                multipart("b", "..\\escape.html", "x".getBytes())).statusCode());
        assertEquals(400, post("/upload", "multipart/form-data; boundary=b",
                multipart("b", "/etc/passwd", "x".getBytes())).statusCode());
    }

    @Test
    void uploadRejectsMissingMultipartBoundary() throws Exception {
        start(1);
        HttpResponse<String> response = post("/upload", "application/json", "{}".getBytes());
        assertEquals(400, response.statusCode());
    }

    @Test
    void existsAndListReflectWorkspaceContent() throws Exception {
        start(1);
        Files.writeString(root.resolve("notes.txt"), "hello");
        HttpResponse<String> exists = get("/exists/notes.txt");
        assertEquals(200, exists.statusCode());
        assertTrue(exists.body().contains("\"exists\":true"));
        HttpResponse<String> missing = get("/exists/nope.txt");
        assertTrue(missing.body().contains("\"exists\":false"));
        HttpResponse<String> listing = get("/list/");
        assertEquals(200, listing.statusCode());
        assertTrue(listing.body().contains("notes.txt"));
    }

    @Test
    void pathEndpointsRejectTraversalTargets() throws Exception {
        start(1);
        assertEquals(400, get("/download/..%2Fsecret.txt").statusCode());
        assertEquals(400, get("/exists/..%2F..%2Fetc").statusCode());
        assertEquals(400, get("/list/..%2F").statusCode());
    }

    @Test
    void unknownRouteReturns404() throws Exception {
        start(1);
        assertEquals(404, get("/nope").statusCode());
    }

    @Test
    @EnabledOnOs(OS.LINUX)
    void executeRunsCommandInWorkspaceRoot() throws Exception {
        start(5);
        HttpResponse<String> response = post("/execute", "application/json",
                "{\"command\":\"echo sandbox-ok; pwd\"}".getBytes(StandardCharsets.UTF_8));
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("sandbox-ok"));
        assertTrue(response.body().contains(root.toRealPath().toString()));
    }

    @Test
    @EnabledOnOs(OS.LINUX)
    void executeRejectsBlankOrOversizedCommands() throws Exception {
        start(5);
        assertEquals(400, post("/execute", "application/json", "{\"command\":\"\"}".getBytes()).statusCode());
        assertEquals(400, post("/execute", "application/json",
                ("{\"command\":\"" + "a".repeat(9000) + "\"}").getBytes()).statusCode());
    }

    @Test
    @EnabledOnOs(OS.LINUX)
    void executeKillsTimedOutCommandTree() throws Exception {
        start(1);
        long before = ProcessHandle.allProcesses().count();
        HttpResponse<String> response = post("/execute", "application/json",
                "{\"command\":\"sh -c 'sleep 30'\"}".getBytes(StandardCharsets.UTF_8));
        assertEquals(200, response.statusCode());
        assertTrue(response.body().contains("\"exit_code\":124"));
        // The sleep child must be gone shortly after the timeout kills the tree.
        Thread.sleep(500);
        assertTrue(ProcessHandle.allProcesses().count() < before + 5,
                "timed-out command tree should not leave stray processes");
    }

    @Test
    @EnabledOnOs(OS.LINUX)
    void concurrentExecutionBeyondLimitReturnsBusy() throws Exception {
        start(1);
        var first = java.util.concurrent.CompletableFuture.supplyAsync(() -> {
            try {
                return post("/execute", "application/json", "{\"command\":\"sleep 2\"}".getBytes());
            } catch (Exception e) { throw new RuntimeException(e); }
        });
        Thread.sleep(300); // let the first command occupy the single execution slot
        HttpResponse<String> second = post("/execute", "application/json",
                "{\"command\":\"echo busy\"}".getBytes(StandardCharsets.UTF_8));
        assertEquals(429, second.statusCode());
        assertEquals(200, first.join().statusCode());
    }
}
