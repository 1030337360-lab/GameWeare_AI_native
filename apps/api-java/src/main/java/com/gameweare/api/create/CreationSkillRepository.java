package com.gameweare.api.create;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/** Product skills are reviewed classpath assets; model tool arguments never become filesystem paths. */
@Component
class CreationSkillRepository {
    record Skill(String id, String name, String description, List<String> tags) {}
    private final Map<String, Skill> catalog = new LinkedHashMap<>();
    private final Map<String, String> contents = new LinkedHashMap<>();

    CreationSkillRepository() throws Exception {
        ObjectMapper json = new ObjectMapper();
        try (var input = new ClassPathResource("creation-skills/catalog.json").getInputStream()) {
            for (Skill skill : json.readValue(input, Skill[].class)) {
                if (!skill.id().matches("[a-z][a-z0-9-]{0,50}") || catalog.putIfAbsent(skill.id(), skill) != null)
                    throw new IllegalStateException("Invalid creation skill catalog");
                try (var file = new ClassPathResource("creation-skills/" + skill.id() + "/SKILL.md").getInputStream()) {
                    byte[] bytes = file.readNBytes(12_001);
                    if (bytes.length > 12_000) throw new IllegalStateException("Creation skill too large");
                    contents.put(skill.id(), new String(bytes, StandardCharsets.UTF_8));
                }
            }
        }
    }

    List<Skill> list() { return List.copyOf(catalog.values()); }
    String read(String id) {
        String content = contents.get(id);
        if (content == null) throw new IllegalArgumentException("Unknown creation skill");
        return content;
    }
}
