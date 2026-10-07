package com.gameweare.api.create;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded, user-reviewed requirements; a model cannot authorize generation. */
record GameBrief(Map<String, String> fields, List<String> questions) {
    static final List<String> FIELDS = List.of("title", "concept", "genre", "coreLoop", "controls", "rules", "victory", "artStyle", "scope");
    static final Map<String, String> LABELS = Map.of("title", "游戏名称", "concept", "主题与玩家角色", "genre", "游戏类型",
            "coreLoop", "核心玩法循环", "controls", "操作方式", "rules", "规则与反馈", "victory", "胜负与目标",
            "artStyle", "美术与氛围", "scope", "首版范围");

    static GameBrief parse(JsonNode node) {
        if (!node.isObject()) throw new IllegalArgumentException("Missing game brief");
        Map<String, String> fields = new LinkedHashMap<>();
        for (String name : FIELDS) {
            JsonNode value = node.path(name);
            if (!value.isMissingNode() && !value.isTextual()) throw new IllegalArgumentException("Invalid brief field");
            String text = value.asText("").strip();
            if (text.length() > 240) throw new IllegalArgumentException("Brief field too long");
            fields.put(name, text);
        }
        List<String> questions = new java.util.ArrayList<>();
        JsonNode q = node.path("questions");
        if (!q.isMissingNode() && !q.isArray()) throw new IllegalArgumentException("Invalid questions");
        for (JsonNode question : q) {
            if (!question.isTextual() || question.asText().length() > 160 || questions.size() >= 3)
                throw new IllegalArgumentException("Invalid questions");
            if (!question.asText().isBlank()) questions.add(question.asText());
        }
        return new GameBrief(fields, List.copyOf(questions));
    }

    boolean ready() {
        return List.of("concept", "coreLoop", "controls", "rules", "victory").stream()
                .allMatch(key -> !fields.getOrDefault(key, "").isBlank());
    }

    Map<String, Object> view() {
        Map<String, Object> out = new LinkedHashMap<>(fields);
        out.put("questions", questions);
        return out;
    }

    String generationPrompt() {
        String name = fields.getOrDefault("title", "");
        if (name.isBlank()) name = fields.getOrDefault("concept", "游戏创作");
        StringBuilder out = new StringBuilder(name + "\n以下需求已由用户审阅确认，请使用 ReAct 迭代实现、校验并交付可玩的单文件 HTML。\n");
        FIELDS.forEach(key -> {
            String value = fields.getOrDefault(key, "");
            if (!value.isBlank()) out.append(LABELS.get(key)).append('：').append(value).append('\n');
        });
        if (!questions.isEmpty()) out.append("尚未指定的细节请采用合理默认值，不要扩大首版范围。\n");
        return out.toString();
    }
}
