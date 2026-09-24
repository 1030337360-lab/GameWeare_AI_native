package com.gameweare.api.create;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/create")
public class CreateController {
    private final CreateService service;
    public CreateController(CreateService service) {
        this.service = service;
    }

    public record InputAsset(String assetId, String objectKey, String publicUrl, String contentType, String filename, long size) {}
    public record JobRequest(@NotBlank String prompt, List<String> files, List<InputAsset> inputAssets,
                             String agentMode, String createType, String projectId) {}
    public record ConfigRequest(@NotBlank String baseUrl, @NotBlank String model,
                                @NotBlank String apiKey, String provider) {}
    public record ConfigTestRequest(String baseUrl, String model, String apiKey, String provider) {}
    public record DecisionRequest(String decision) {}
    public record SelectionRequest(String candidateId) {}

    @PostMapping("/jobs")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> create(@RequestAttribute("userId") String userId,
                                      @RequestHeader(value = "X-Idempotency-Key", required = false) String key,
                                      @Valid @RequestBody JobRequest request) {
        try { return service.create(userId, request, key); }
        catch (DuplicateKeyException race) {
            if (key == null || key.isBlank()) throw race;
            return service.existingForKey(userId, request, key);
        }
    }

    @GetMapping("/jobs/{id}")
    public Map<String, Object> job(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.job(userId, id);
    }

    @PostMapping("/jobs/{id}/publish")
    public Map<String, Object> publish(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.publish(userId, id);
    }

    @GetMapping("/projects")
    public List<Map<String, Object>> projects(@RequestAttribute("userId") String userId) {
        return service.projects(userId);
    }

    @GetMapping("/projects/{id}")
    public Map<String, Object> project(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.project(userId, id);
    }

    @DeleteMapping("/projects/{id}")
    public Map<String, Object> deleteProject(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.deleteProject(userId, id);
    }

    @GetMapping("/projects/{id}/preview")
    public Map<String, Object> preview(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.preview(userId, id);
    }

    @GetMapping("/recent-game")
    public Map<String, Object> recentGame(@RequestAttribute("userId") String userId) { return service.recentGame(userId); }

    @GetMapping("/runs/{id}")
    public Map<String, Object> run(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.job(userId, id);
    }

    @GetMapping("/runs/{id}/steps")
    public List<Map<String, Object>> steps(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.steps(userId, id, 0);
    }

    @GetMapping("/runs/{id}/plan-preview")
    public Map<String, Object> planPreview(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.planPreview(userId, id);
    }

    @PostMapping("/runs/{id}/plan-decision")
    public Map<String, Object> planDecision(@RequestAttribute("userId") String userId, @PathVariable String id,
                                            @RequestBody DecisionRequest request) {
        return service.planDecision(userId, id, request.decision());
    }

    @GetMapping("/runs/{id}/decentralized-previews")
    public Map<String, Object> decentralizedPreviews(@RequestAttribute("userId") String userId, @PathVariable String id) {
        return service.decentralizedPreviews(userId, id);
    }

    @PostMapping("/runs/{id}/decentralized-selection")
    public Map<String, Object> selectCandidate(@RequestAttribute("userId") String userId, @PathVariable String id,
                                               @RequestBody SelectionRequest request) {
        return service.selectCandidate(userId, id, request.candidateId());
    }

    @PostMapping("/runs/{id}/decentralized-confirm")
    public Map<String, Object> confirmCandidate(@RequestAttribute("userId") String userId, @PathVariable String id,
                                                @RequestBody DecisionRequest request) {
        return service.confirmCandidate(userId, id, request.decision());
    }

    @GetMapping(value = "/runs/{id}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@RequestAttribute("userId") String userId, @PathVariable String id,
                             @RequestParam(defaultValue = "0") int afterStepNo) {
        return service.events(userId, id, afterStepNo);
    }

    @GetMapping("/ai-config")
    public Map<String, Object> config(@RequestAttribute("userId") String userId) { return service.config(userId); }

    @PutMapping("/ai-config")
    public Map<String, Object> saveConfig(@RequestAttribute("userId") String userId,
                                          @Valid @RequestBody ConfigRequest request) {
        return service.saveConfig(userId, request);
    }

    @PostMapping("/ai-config/test")
    public Map<String, Object> testConfig(@RequestAttribute("userId") String userId,
                                          @RequestBody(required = false) ConfigTestRequest request) {
        return service.testConfig(userId, request);
    }
}
