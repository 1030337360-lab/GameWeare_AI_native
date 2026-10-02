package com.gameweare.api.maintenance;

import com.gameweare.api.create.CreateController;
import com.gameweare.api.create.CreateService;
import io.minio.MinioClient;
import io.minio.RemoveObjectArgs;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/maintenance")
public class MaintenanceController {
    private final MaintenanceService service;
    public MaintenanceController(MaintenanceService service) { this.service = service; }

    @GetMapping("/overview")
    public Map<String, Object> overview(HttpServletRequest r) { return service.overview(actor(r)); }
    @GetMapping("/jobs")
    public List<Map<String, Object>> jobs(@RequestParam(required=false) String status, @RequestParam(defaultValue="50") int limit, HttpServletRequest r) {
        return service.jobs(actor(r), status, limit);
    }
    @GetMapping("/jobs/{id}/trace")
    public Map<String, Object> jobTrace(@PathVariable String id, HttpServletRequest r) {
        return service.jobTrace(actor(r), id);
    }
    @GetMapping("/create-runs/failed")
    public List<Map<String, Object>> failed(@RequestParam(defaultValue="20") int limit, HttpServletRequest r) {
        return service.failed(actor(r), limit);
    }
    @PostMapping("/jobs/{id}/mark-reviewed")
    public Map<String, Object> reviewJob(@PathVariable String id, @RequestParam(defaultValue="Reviewed by maintainer") String reason, HttpServletRequest r) {
        return service.reviewJob(actor(r), id, reason);
    }
    @PostMapping("/jobs/{id}/retry")
    public Map<String, Object> retry(@PathVariable String id, HttpServletRequest r) { return service.retry(actor(r), id); }
    @GetMapping("/games")
    public List<Map<String, Object>> games(@RequestParam(required=false) String status, @RequestParam(required=false) String q,
                                           @RequestParam(defaultValue="50") int limit, HttpServletRequest r) {
        return service.games(actor(r), status, q, limit);
    }
    @PatchMapping("/games/{id}")
    public Map<String, Object> updateGame(@PathVariable String id, @RequestBody Map<String, String> body, HttpServletRequest r) {
        return service.updateGame(actor(r), id, body);
    }
    @PostMapping("/games/{id}/moderate")
    public Map<String, Object> moderate(@PathVariable String id, @RequestBody Map<String, String> body, HttpServletRequest r) {
        return service.moderate(actor(r), id, body);
    }
    @GetMapping("/assets")
    public List<Map<String, Object>> assets(@RequestParam(required=false) String gameId, @RequestParam(required=false) String jobId,
                                            @RequestParam(defaultValue="50") int limit, HttpServletRequest r) {
        return service.assets(actor(r), gameId, jobId, limit);
    }
    @DeleteMapping("/assets/{id}")
    public Map<String, Object> deleteAsset(@PathVariable String id, HttpServletRequest r) { return service.deleteAsset(actor(r), id); }
    @GetMapping("/reviews")
    public List<Map<String, Object>> reviews(@RequestParam(required=false) String status, @RequestParam(defaultValue="50") int limit, HttpServletRequest r) {
        return service.reviews(actor(r), status, limit);
    }
    @GetMapping("/agent-usage")
    public List<Map<String, Object>> agentUsage(@RequestParam(required=false) String jobId,
                                                @RequestParam(defaultValue="50") int limit, HttpServletRequest r) {
        return service.agentUsage(actor(r), jobId, limit);
    }

    private String actor(HttpServletRequest request) {
        Object id = request.getAttribute("userId");
        if (id == null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Login required");
        return id.toString();
    }
}
