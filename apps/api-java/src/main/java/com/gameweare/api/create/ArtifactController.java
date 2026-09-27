package com.gameweare.api.create;

import java.util.LinkedHashMap;
import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/create/artifacts")
public class ArtifactController {
    private final ArtifactValidator validator;
    private final ArtifactService service;

    public ArtifactController(ArtifactValidator validator, ArtifactService service) {
        this.validator = validator;
        this.service = service;
    }

    public record ArtifactRequest(String prompt, String html, String projectId) {}

    @PostMapping("/validate")
    public Map<String, Object> validate(@RequestAttribute("userId") String userId,
                                        @RequestBody ArtifactRequest request) {
        ArtifactValidator.Result result = validator.validate(request.html());
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("ok", result.ok());
        response.put("format", result.format());
        response.put("diagnostics", result.diagnostics());
        return response;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> receive(@RequestAttribute("userId") String userId,
                                       @RequestHeader(value = "X-Idempotency-Key", required = false) String key,
                                       @RequestBody ArtifactRequest request) {
        return service.receive(userId, request, key);
    }
}
