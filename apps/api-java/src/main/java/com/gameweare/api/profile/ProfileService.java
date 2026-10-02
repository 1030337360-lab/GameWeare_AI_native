package com.gameweare.api.profile;

import com.gameweare.api.profile.dao.ProfileMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@Service
class ProfileService {
    private final ProfileMapper profile;
    ProfileService(ProfileMapper profile) { this.profile = profile; }

    public Map<String, Object> activity(String userId) {
        List<Map<String, Object>> plays = profile.recentPlays(userId);
        List<Map<String, Object>> recent = new ArrayList<>();
        for (Map<String, Object> row : plays) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("eventId", row.get("event_id")); item.put("eventType", row.get("event_type"));
            item.put("playedAt", row.get("created_at")); item.put("game", game(row, userId)); recent.add(item);
        }
        return Map.of("recentPlays", recent, "projects", projects(userId));
    }

    public Map<String, Object> project(String userId, String projectId) {
        Map<String, Object> found = profile.project(projectId, userId);
        if (found == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
        Map<String, Object> project = projectIndex(found);
        List<Map<String, Object>> rows = profile.projectRuns(projectId, userId);
        List<Map<String, Object>> runs = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            String jobId = row.get("id").toString();
            List<Map<String, Object>> stepRows = profile.runSteps(jobId);
            List<Map<String, Object>> steps = new ArrayList<>();
            StringBuilder feedback = new StringBuilder();
            for (Map<String, Object> step : stepRows) {
                String message = sanitize((String) step.get("message"), 900);
                Map<String, Object> detail = new LinkedHashMap<>();
                detail.put("stepNo", step.get("step_no")); detail.put("stage", step.get("stage"));
                detail.put("status", step.get("status")); detail.put("inputSummary", null);
                detail.put("outputSummary", message); detail.put("metrics", Map.of());
                detail.put("createdAt", step.get("created_at"));
                detail.put("recordType", "failed".equals(step.get("status")) ? "error" : "lifecycle");
                steps.add(detail);
                if (message != null && !message.isBlank() && feedback.length() < 900) feedback.append(message).append('\n');
            }
            String prompt = sanitize((String) row.get("prompt"), 900);
            String llm = sanitize(feedback.toString(), 900);
            Map<String, Object> run = new LinkedHashMap<>();
            run.put("runId", jobId); run.put("jobId", jobId); run.put("status", row.get("status"));
            run.put("createType", row.get("create_type")); run.put("agentMode", row.get("agent_mode"));
            run.put("promptSummary", summary(prompt)); run.put("promptFull", prompt);
            run.put("llmSummary", summary(llm)); run.put("llmFull", llm);
            run.put("createdAt", row.get("created_at"));
            run.put("completedAt", List.of("completed","failed","cancelled").contains(row.get("status")) ? row.get("updated_at") : null);
            run.put("steps", steps); runs.add(run);
        }
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("project", project);
        Object gameId = found.get("game_id");
        Map<String, Object> published = gameId == null ? null : profile.publicGame(gameId.toString());
        response.put("game", published == null ? null : game(published, userId));
        response.put("runs", runs);
        return response;
    }

    private List<Map<String, Object>> projects(String userId) {
        return profile.projects(userId).stream().map(this::projectIndex).toList();
    }

    private Map<String, Object> projectIndex(Map<String, Object> row) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("projectId", row.get("project_id")); out.put("title", row.get("title"));
        out.put("status", row.get("status")); out.put("gameId", row.get("game_id"));
        out.put("gameSlug", row.get("game_slug")); out.put("latestRunId", row.get("latest_run_id"));
        out.put("latestRunStatus", row.get("latest_run_status")); out.put("updatedAt", row.get("updated_at"));
        return out;
    }

    private Map<String, Object> game(Map<String, Object> row, String userId) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.get("slug")); out.put("title", row.get("title")); out.put("author", row.get("author"));
        out.put("description", row.get("description"));
        out.put("tags", profile.gameTags(row.get("game_id").toString()));
        out.put("publishedAt", row.get("published_at"));
        out.put("coverUrl", "/games/" + row.get("slug") + "/cover");
        out.put("plays", row.get("plays_count")); out.put("likes", row.get("likes_count"));
        out.put("favorites", row.get("favorites_count"));
        out.put("likedByMe", profile.likeCount(row.get("game_id").toString(), userId) > 0);
        out.put("favoritedByMe", profile.favoriteCount(row.get("game_id").toString(), userId) > 0);
        out.put("section", "Recently Created");
        return out;
    }

    private String summary(String text) {
        if (text == null || text.isBlank()) return "";
        String[] words = text.trim().split("\\s+");
        return String.join(" ", java.util.Arrays.copyOf(words, Math.min(words.length, 20))) + (words.length > 20 ? "..." : "");
    }

    private String sanitize(String text, int max) {
        if (text == null) return "";
        String clean = text.replaceAll("(?i)authorization\\s*:\\s*(?:Bearer|Basic)\\s+[^\\s,;]+", "[redacted]")
                .replaceAll("(?i)(api[_-]?key|token|secret|password|authorization)\\s*[:=]\\s*[^\\s,;]+", "[redacted]")
                .replaceAll("data:[^;,\\s]+;base64,[A-Za-z0-9+/=]+", "[redacted-base64]");
        return clean.length() <= max ? clean : clean.substring(0, max) + "... [truncated]";
    }
}
