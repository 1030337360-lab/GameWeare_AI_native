package com.gameweare.api;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class GameweareApplication {
    public static void main(String[] args) {
        SpringApplication.run(GameweareApplication.class, args);
    }
}
