package com.gameweare.api.config;

import io.minio.MinioClient;
import io.minio.BucketExistsArgs;
import io.minio.MakeBucketArgs;
import org.flywaydb.core.Flyway;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import javax.sql.DataSource;

@Configuration
public class InfrastructureConfig {
    public static final String CREATE_EXCHANGE = "gameweare.create";
    public static final String CREATE_QUEUE = "gameweare.create.jobs";
    public static final String CREATE_DEAD_EXCHANGE = "gameweare.create.dead";
    public static final String CREATE_DEAD_QUEUE = "gameweare.create.dead.jobs";

    @Bean
    Flyway flyway(DataSource dataSource) {
        Flyway flyway = Flyway.configure().dataSource(dataSource).load();
        flyway.migrate();
        return flyway;
    }

    @Bean
    MinioClient minioClient(@Value("${gameweare.minio.endpoint}") String endpoint,
                            @Value("${gameweare.minio.access-key}") String accessKey,
                            @Value("${gameweare.minio.secret-key}") String secretKey) {
        return MinioClient.builder().endpoint(endpoint).credentials(accessKey, secretKey).build();
    }

    @Bean
    CommandLineRunner ensureGameBucket(MinioClient minio, @Value("${gameweare.minio.bucket}") String bucket) {
        return args -> {
            if (!minio.bucketExists(BucketExistsArgs.builder().bucket(bucket).build())) {
                minio.makeBucket(MakeBucketArgs.builder().bucket(bucket).build());
            }
        };
    }

    // Spring Boot 4 auto-configures Jackson 3 (tools.jackson) only; GoogleOAuthService still
    // consumes the Jackson 2 ObjectMapper directly, so expose one explicitly.
    @Bean
    com.fasterxml.jackson.databind.ObjectMapper legacyObjectMapper() {
        return new com.fasterxml.jackson.databind.ObjectMapper();
    }

    @Bean DirectExchange createExchange() { return new DirectExchange(CREATE_EXCHANGE, true, false); }
    @Bean DirectExchange createDeadExchange() { return new DirectExchange(CREATE_DEAD_EXCHANGE, true, false); }
    @Bean Queue createQueue() {
        return org.springframework.amqp.core.QueueBuilder.durable(CREATE_QUEUE)
                .deadLetterExchange(CREATE_DEAD_EXCHANGE).deadLetterRoutingKey("job.dead").build();
    }
    @Bean Queue createDeadQueue() { return new Queue(CREATE_DEAD_QUEUE, true); }
    @Bean Binding createBinding(Queue createQueue, DirectExchange createExchange) {
        return BindingBuilder.bind(createQueue).to(createExchange).with("job.created");
    }
    @Bean Binding createDeadBinding(Queue createDeadQueue, DirectExchange createDeadExchange) {
        return BindingBuilder.bind(createDeadQueue).to(createDeadExchange).with("job.dead");
    }

}
