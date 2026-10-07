package com.gameweare.api.create;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/create/chat")
public class CreationChatController {
    private final CreationChatService chats;
    private final CreationSkillRepository skills;
    CreationChatController(CreationChatService chats, CreationSkillRepository skills) {
        this.chats = chats; this.skills = skills;
    }
    public record Start(@NotBlank String id, String createType, String projectId, String fundingMode, String voucherId) {}
    public record Turn(@NotBlank @Size(max=2000) String message, @NotBlank String requestId, @Min(0) int revision) {}
    public record Confirm(@Min(0) int revision) {}

    @GetMapping("/skills") public List<CreationSkillRepository.Skill> skills() { return skills.list(); }
    @GetMapping("/sessions") public List<Map<String, Object>> list(@RequestAttribute("userId") String user) { return chats.list(user); }
    @PostMapping("/sessions") @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> start(@RequestAttribute("userId") String user, @Valid @RequestBody Start input) {
        return chats.start(user, input);
    }
    @GetMapping("/sessions/{id}") public Map<String, Object> get(@RequestAttribute("userId") String user, @PathVariable String id) {
        return chats.get(user, id);
    }
    @PostMapping("/sessions/{id}/messages")
    public Map<String, Object> turn(@RequestAttribute("userId") String user, @PathVariable String id, @Valid @RequestBody Turn input) {
        return chats.turn(user, id, input);
    }
    @PostMapping("/sessions/{id}/confirm") @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, Object> confirm(@RequestAttribute("userId") String user, @PathVariable String id, @Valid @RequestBody Confirm input) {
        return chats.confirm(user, id, input.revision());
    }
}
