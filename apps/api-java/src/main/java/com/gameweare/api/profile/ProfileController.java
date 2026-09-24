package com.gameweare.api.profile;

import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/profile")
public class ProfileController {
    private final ProfileService profile;
    public ProfileController(ProfileService profile) { this.profile = profile; }

    @GetMapping("/activity")
    public Map<String, Object> activity(HttpServletRequest request) { return profile.activity(user(request)); }

    @GetMapping("/projects/{id}")
    public Map<String, Object> project(@PathVariable String id, HttpServletRequest request) {
        return profile.project(user(request), id);
    }

    private String user(HttpServletRequest request) {
        Object id = request.getAttribute("userId");
        if (id == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Login required");
        return id.toString();
    }
}

@Service
class ProfileService {
    private final JdbcTemplate jdbc;
    ProfileService(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public Map<String, Object> activity(String userId) {
        List<Map<String, Object>> plays = jdbc.queryForList("""
            SELECT pe.id AS event_id, pe.event_type, pe.created_at, g.id AS game_id, g.slug, g.title, g.description,
                   g.cover_object_key, g.plays_count, g.likes_count, g.favorites_count,
                   g.published_at, u.display_name AS author
            FROM play_events pe JOIN games g ON g.id=pe.game_id JOIN users u ON u.id=g.author_id
            WHERE pe.user_id=? AND g.publish_status='published' AND g.visibility='public'
              AND pe.id=(SELECT pe2.id FROM play_events pe2 WHERE pe2.game_id=pe.game_id AND pe2.user_id=? ORDER BY pe2.created_at DESC LIMIT 1)
            ORDER BY pe.created_at DESC LIMIT 3
            """, userId, userId);
        List<Map<String, Object>> recent = new ArrayList<>();
        for (Map<String, Object> row : plays) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("eventId", row.get("event_id")); item.put("eventType", row.get("event_type"));
            item.put("playedAt", row.get("created_at")); item.put("game", game(row, userId)); recent.add(item);
        }
        return Map.of("recentPlays", recent, "projects", projects(userId));
    }

    public Map<String, Object> project(String userId, String projectId) {
        List<Map<String, Object>> found = jdbc.queryForList("""
            SELECT p.id AS project_id,p.title,p.status,p.game_id,g.slug AS game_slug,p.updated_at,
                   (SELECT j.id FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_id,
                   (SELECT j.status FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_status
            FROM create_projects p LEFT JOIN games g ON g.id=p.game_id
            WHERE p.id=? AND p.user_id=? AND p.status<>'deleted' LIMIT 1
            """, projectId, userId);
        if (found.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Project not found");
        Map<String, Object> project = projectIndex(found.get(0));
        List<Map<String, Object>> rows = jdbc.queryForList("""
            SELECT id,prompt,status,create_type,agent_mode,created_at,updated_at
            FROM create_jobs WHERE project_id=? AND user_id=? ORDER BY created_at DESC
            """, projectId, userId);
        List<Map<String, Object>> runs = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            String jobId = row.get("id").toString();
            List<Map<String, Object>> stepRows = jdbc.queryForList("""
                SELECT step_no,stage,status,message,created_at FROM create_run_steps
                WHERE job_id=? ORDER BY step_no
                """, jobId);
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
        Object gameId = found.get(0).get("game_id");
        List<Map<String, Object>> games = gameId == null ? List.of() : jdbc.queryForList("""
            SELECT g.id AS game_id,g.slug,g.title,g.description,g.cover_object_key,g.plays_count,g.likes_count,
                   g.favorites_count,g.published_at,u.display_name AS author
            FROM games g JOIN users u ON u.id=g.author_id
            WHERE g.id=? AND g.publish_status='published' AND g.visibility='public'
            """, gameId);
        response.put("game", games.isEmpty() ? null : game(games.get(0), userId));
        response.put("runs", runs);
        return response;
    }

    private List<Map<String, Object>> projects(String userId) {
        List<Map<String, Object>> rows = jdbc.queryForList("""
            SELECT p.id AS project_id,p.title,p.status,p.game_id,g.slug AS game_slug,p.updated_at,
                   (SELECT j.id FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_id,
                   (SELECT j.status FROM create_jobs j WHERE j.project_id=p.id ORDER BY j.created_at DESC LIMIT 1) AS latest_run_status
            FROM create_projects p LEFT JOIN games g ON g.id=p.game_id
            WHERE p.user_id=? AND p.status<>'deleted' ORDER BY p.updated_at DESC LIMIT 100
            """, userId);
        return rows.stream().map(this::projectIndex).toList();
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
        out.put("tags", jdbc.queryForList("SELECT t.name FROM tags t JOIN game_tags gt ON gt.tag_id=t.id WHERE gt.game_id=? ORDER BY t.name", String.class, row.get("game_id")));
        out.put("publishedAt", row.get("published_at"));
        out.put("coverUrl", row.get("cover_object_key") == null ? "" : "/games/" + row.get("slug") + "/cover");
        out.put("plays", row.get("plays_count")); out.put("likes", row.get("likes_count"));
        out.put("favorites", row.get("favorites_count"));
        out.put("likedByMe", jdbc.queryForObject("SELECT COUNT(*) FROM game_likes WHERE game_id=? AND user_id=?", Long.class, row.get("game_id"), userId) > 0);
        out.put("favoritedByMe", jdbc.queryForObject("SELECT COUNT(*) FROM game_favorites WHERE game_id=? AND user_id=?", Long.class, row.get("game_id"), userId) > 0);
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
