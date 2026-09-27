package com.gameweare.api.catalog;

import com.gameweare.api.create.ArtifactValidator;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Installs the bundled quiz as an ordinary published game on a fresh Compose database. */
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
public class BuiltInGameSeeder implements ApplicationRunner {
    private static final Logger log = LoggerFactory.getLogger(BuiltInGameSeeder.class);
    private static final String SLUG = "java-interview-quiz";
    private static final String EMAIL = "built-in-java-quiz@gameweare.invalid";
    private static final String USER_ID = stableId("author");
    private static final String GAME_ID = stableId("game");
    private static final String VERSION_ID = stableId("version-1");
    private static final String ASSET_ID = stableId("asset-1");
    private static final String OBJECT_KEY = "games/" + GAME_ID + "/" + VERSION_ID + "/index.html";
    private final JdbcTemplate jdbc;
    private final MinioClient minio;
    private final ArtifactValidator validator;
    private final TransactionTemplate transaction;
    private final String bucket;

    public BuiltInGameSeeder(JdbcTemplate jdbc, MinioClient minio, ArtifactValidator validator,
            PlatformTransactionManager transactionManager,
            @Value("${gameweare.minio.bucket}") String bucket) {
        this.jdbc = jdbc;
        this.minio = minio;
        this.validator = validator;
        this.transaction = new TransactionTemplate(transactionManager);
        this.bucket = bucket;
    }

    @Override
    public void run(org.springframework.boot.ApplicationArguments args) throws Exception {
        List<String> existing = jdbc.queryForList("SELECT id FROM games WHERE slug=?", String.class, SLUG);
        if (!existing.isEmpty()) {
            if (!GAME_ID.equals(existing.get(0))) log.warn("Bundled quiz slug already belongs to another game; skipping seed");
            return;
        }

        byte[] html = new ClassPathResource("seed/java-interview-quiz/index.html").getInputStream().readAllBytes();
        var validation = validator.validate(new String(html, StandardCharsets.UTF_8));
        if (!validation.ok()) throw new IllegalStateException("Bundled quiz failed HTML validation: " + validation.diagnostics());
        html = validation.normalizedHtml().getBytes(StandardCharsets.UTF_8);
        try (var input = new ByteArrayInputStream(html)) {
            minio.putObject(PutObjectArgs.builder().bucket(bucket).object(OBJECT_KEY)
                    .stream(input, html.length, -1).contentType("text/html; charset=utf-8").build());
        }
        long size = html.length;
        transaction.executeWithoutResult(status -> {
            jdbc.update("INSERT IGNORE INTO users(id,email,password_hash,display_name,role) VALUES(?,?,?,?,'user')",
                    USER_ID, EMAIL, new BCryptPasswordEncoder().encode(UUID.randomUUID().toString()), "GameWeare 官方");
            List<String> author = jdbc.queryForList("SELECT id FROM users WHERE email=?", String.class, EMAIL);
            if (author.size() != 1 || !USER_ID.equals(author.get(0)))
                throw new IllegalStateException("Bundled quiz author account conflicts with existing user");
            jdbc.update("""
                    INSERT IGNORE INTO games(id,slug,title,description,author_id,publish_status,visibility)
                    VALUES(?,?,?,?,?,'draft','private')
                    """, GAME_ID, SLUG, "Java 面试知识闯关",
                    "内置 Java 知识问答游戏：80 道题，按八个方向抽取基础与进阶题，每局挑战 16 题。", USER_ID);
            List<String> game = jdbc.queryForList("SELECT id FROM games WHERE slug=?", String.class, SLUG);
            if (game.size() != 1 || !GAME_ID.equals(game.get(0)))
                throw new IllegalStateException("Bundled quiz slug conflicts with existing game");
            jdbc.update("""
                    INSERT IGNORE INTO game_versions(id,game_id,version_no,entry_object_key,runtime,
                        build_status,safety_status,entry_file,storage_prefix)
                    VALUES(?,?,1,?,'iframe-html5','passed','passed','index.html',?)
                    """, VERSION_ID, GAME_ID, OBJECT_KEY, "games/" + GAME_ID + "/" + VERSION_ID);
            jdbc.update("""
                    INSERT IGNORE INTO assets(id,owner_id,game_id,version_id,kind,bucket,object_key,content_type,size_bytes)
                    VALUES(?,?,?,?,'html',?,?,?,?)
                    """, ASSET_ID, USER_ID, GAME_ID, VERSION_ID, bucket, OBJECT_KEY, "text/html; charset=utf-8", size);
            jdbc.update("""
                    UPDATE games SET current_version_id=?, publish_status='published', visibility='public',
                        published_at=COALESCE(published_at,UTC_TIMESTAMP(6))
                    WHERE id=? AND slug=? AND author_id=? AND current_version_id IS NULL
                    """, VERSION_ID, GAME_ID, SLUG, USER_ID);
        });
        log.info("Bundled Java interview quiz is available at /play/{}/manifest", SLUG);
    }

    private static String stableId(String part) {
        return UUID.nameUUIDFromBytes(("gameweare:built-in:java-interview-quiz:" + part)
                .getBytes(StandardCharsets.UTF_8)).toString();
    }
}
