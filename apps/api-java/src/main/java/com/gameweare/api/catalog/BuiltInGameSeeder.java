package com.gameweare.api.catalog;

import com.gameweare.api.catalog.dao.BuiltInGameMapper;
import com.gameweare.api.create.ArtifactValidator;
import io.minio.MinioClient;
import io.minio.PutObjectArgs;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.core.io.ClassPathResource;
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
    private final BuiltInGameMapper games;
    private final MinioClient minio;
    private final ArtifactValidator validator;
    private final GameSlugBloomFilter bloomFilter;
    private final TransactionTemplate transaction;
    private final String bucket;

    public BuiltInGameSeeder(BuiltInGameMapper games, MinioClient minio, ArtifactValidator validator,
            GameSlugBloomFilter bloomFilter,
            PlatformTransactionManager transactionManager,
            @Value("${gameweare.minio.bucket}") String bucket) {
        this.games = games;
        this.minio = minio;
        this.validator = validator;
        this.bloomFilter = bloomFilter;
        this.transaction = new TransactionTemplate(transactionManager);
        this.bucket = bucket;
    }

    @Override
    public void run(org.springframework.boot.ApplicationArguments args) throws Exception {
        String existing = games.gameIdBySlug(SLUG);
        if (existing != null) {
            if (!GAME_ID.equals(existing)) log.warn("Bundled quiz slug already belongs to another game; skipping seed");
            else {
                if (games.publicGameCount(GAME_ID) > 0) bloomFilter.addBeforePublish(SLUG);
            }
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
        // A scheduled Bloom seed may finish before this startup fixture is published.
        // Register the slug first so a ready filter cannot reject the new public game.
        bloomFilter.addBeforePublish(SLUG);
        transaction.executeWithoutResult(status -> {
            games.insertAuthor(USER_ID, EMAIL, new BCryptPasswordEncoder().encode(UUID.randomUUID().toString()),
                    "GameWeare 官方");
            String author = games.authorIdByEmail(EMAIL);
            if (!USER_ID.equals(author))
                throw new IllegalStateException("Bundled quiz author account conflicts with existing user");
            games.insertGame(GAME_ID, SLUG, "Java 面试知识闯关",
                    "内置 Java 知识问答游戏：80 道题，按八个方向抽取基础与进阶题，每局挑战 16 题。", USER_ID);
            String game = games.gameIdBySlug(SLUG);
            if (!GAME_ID.equals(game))
                throw new IllegalStateException("Bundled quiz slug conflicts with existing game");
            games.insertVersion(VERSION_ID, GAME_ID, OBJECT_KEY, "games/" + GAME_ID + "/" + VERSION_ID);
            games.insertAsset(ASSET_ID, USER_ID, GAME_ID, VERSION_ID, bucket, OBJECT_KEY,
                    "text/html; charset=utf-8", size);
            games.publish(VERSION_ID, GAME_ID, SLUG, USER_ID);
        });
        log.info("Bundled Java interview quiz is available at /play/{}/manifest", SLUG);
    }

    private static String stableId(String part) {
        return UUID.nameUUIDFromBytes(("gameweare:built-in:java-interview-quiz:" + part)
                .getBytes(StandardCharsets.UTF_8)).toString();
    }
}
