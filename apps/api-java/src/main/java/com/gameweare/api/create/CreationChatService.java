package com.gameweare.api.create;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.gameweare.api.create.dao.CreationChatMapper;
import java.util.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

@Service
class CreationChatService {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final DefaultRedisScript<Long> RATE = new DefaultRedisScript<>(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", Long.class);
    private final CreationChatMapper chats;
    private final CreateService creation;
    private final CreationGuideModel model;
    private final TransactionTemplate tx;
    private final StringRedisTemplate redis;

    CreationChatService(CreationChatMapper chats, CreateService creation, CreationGuideModel model,
                        TransactionTemplate tx, StringRedisTemplate redis) {
        this.chats=chats; this.creation=creation; this.model=model; this.tx=tx; this.redis=redis;
    }

    @Transactional
    public Map<String, Object> start(String user, CreationChatController.Start input) {
        uuid(input.id());
        Map<String, Object> existing = chats.find(input.id(), user);
        if (existing != null && !existing.isEmpty()) return view(existing, true);
        String type = input.createType() == null ? "init" : input.createType();
        String funding = input.fundingMode() == null ? "byok" : input.fundingMode();
        if (!Set.of("init", "opt").contains(type) || !Set.of("byok", "voucher").contains(funding))
            throw error(HttpStatus.BAD_REQUEST, "Invalid chat creation mode");
        if ("opt".equals(type)) {
            uuid(input.projectId());
            if (chats.ownedProject(input.projectId(), user) != 1) throw error(HttpStatus.NOT_FOUND, "Project not found");
        } else if (input.projectId() != null) throw error(HttpStatus.BAD_REQUEST, "New chat must not reuse a project");
        validateFunding(user, funding, input.voucherId());
        rate(user);
        chats.insert(input.id(), user, type, input.projectId(), funding, input.voucherId());
        return view(owned(input.id(), user), true);
    }

    public List<Map<String, Object>> list(String user) {
        return chats.list(user).stream().map(row -> view(row, false)).toList();
    }
    public Map<String, Object> get(String user, String id) { uuid(id); return view(owned(id, user), true); }

    public Map<String, Object> turn(String user, String id, CreationChatController.Turn input) {
        uuid(id); uuid(input.requestId());
        if (input.message() == null || input.message().isBlank() || input.message().length() > 2000 || input.revision() < 0)
            throw error(HttpStatus.BAD_REQUEST, "Invalid chat message");
        Map<String, Object> row = owned(id, user);
        if (chats.completedRequest(id, input.requestId()) > 0) {
            if (!input.message().strip().equals(chats.requestMessage(id, input.requestId())))
                throw error(HttpStatus.CONFLICT, "同一请求编号不能用于不同的消息。");
            return view(row, true);
        }
        if (input.revision() >= 30) throw error(HttpStatus.CONFLICT, "本轮访谈已达30轮，请确认画像或开始新的对话。");
        validateFunding(user, row.get("funding_mode").toString(), (String) row.get("voucher_id"));
        rate(user);
        Map<String, Object> config = creation.configRowForJob(user, row);
        if (config == null) throw error(HttpStatus.CONFLICT, "Configure an AI provider first");
        String key = creation.keyFor(config);
        // The lease token is distinct from the retry/idempotency key: an expired caller cannot commit or release a newer lease.
        String leaseToken = UUID.randomUUID().toString();
        int claimed = chats.claim(id, user, leaseToken, input.revision());
        if (claimed != 1) throw error(HttpStatus.CONFLICT, "对话已更新或正在回复，请刷新后重试。");
        try {
            List<Map<String, Object>> stored = chats.messages(id);
            List<Map<String, String>> history = stored.stream().skip(Math.max(0, stored.size()-12))
                    .map(m -> Map.of("role", m.get("role").toString(), "content", m.get("content").toString())).toList();
            String context = "createType=" + row.get("create_type");
            if (row.get("project_id") != null) context += "\n" + JSON.writeValueAsString(creation.project(user, row.get("project_id").toString()));
            CreationGuideModel.Reply reply = model.respond(config.get("base_url").toString(), config.get("model").toString(),
                    key, history, Objects.toString(row.get("brief_json"), "{}"), input.message().strip(), context);
            tx.executeWithoutResult(status -> {
                if (chats.finish(id, user, leaseToken, input.revision(), json(reply.brief().view())) != 1)
                    throw error(HttpStatus.CONFLICT, "这轮回复已过期，请刷新对话。");
                chats.message(UUID.randomUUID().toString(), id, input.requestId(), "user", input.message().strip(), "[]",
                        input.revision()*2, 0, 0);
                chats.message(UUID.randomUUID().toString(), id, input.requestId(), "assistant", reply.text(), json(reply.skills()),
                        input.revision()*2+1, reply.inputTokens(), reply.outputTokens());
            });
            return view(owned(id, user), true);
        } catch (ResponseStatusException failure) { throw failure;
        } catch (Exception failure) {
            throw error(HttpStatus.BAD_GATEWAY, "创作助手暂时无法回复；这一轮未保存，请稍后重试。请检查模型配置。");
        } finally {
            chats.release(id, user, leaseToken);
        }
    }

    @Transactional
    public Map<String, Object> confirm(String user, String id, int revision) {
        uuid(id);
        Map<String, Object> row = chats.lock(id, user);
        if (row == null || row.isEmpty()) throw error(HttpStatus.NOT_FOUND, "Chat not found");
        if ("confirmed".equals(row.get("status"))) return creation.job(user, row.get("job_id").toString());
        if ("replying".equals(row.get("status")) && replyExpired(row)) {
            chats.release(id, user, row.get("pending_request_id").toString());
            row.put("status", "draft");
        }
        if (!"draft".equals(row.get("status")) || revision != ((Number) row.get("revision")).intValue())
            throw error(HttpStatus.CONFLICT, "对话已更新或正在回复，请重新审阅画像。");
        GameBrief brief = brief(row);
        if (brief == null || !brief.ready()) throw error(HttpStatus.CONFLICT, "请先明确主题、玩法、操作、规则和目标。");
        Map<String, Object> job = creation.create(user, new CreateController.JobRequest(brief.generationPrompt(), List.of(), List.of(),
                "react", row.get("create_type").toString(), (String) row.get("project_id"),
                row.get("funding_mode").toString(), (String) row.get("voucher_id")), "chat:" + id);
        if (chats.confirm(id, user, revision, job.get("id").toString()) != 1)
            throw error(HttpStatus.CONFLICT, "Chat confirmation changed concurrently");
        return job;
    }

    private void validateFunding(String user, String funding, String voucherId) {
        if ("voucher".equals(funding)) {
            uuid(voucherId);
            if (!creation.officialConfigured()) throw error(HttpStatus.SERVICE_UNAVAILABLE, "Official model is not configured");
            if (chats.availableVoucher(voucherId, user) != 1) throw error(HttpStatus.CONFLICT, "生成券不可用，请使用有效生成券开始对话。");
        } else {
            if (voucherId != null) throw error(HttpStatus.BAD_REQUEST, "voucherId requires voucher funding");
            if (creation.configRow(user) == null) throw error(HttpStatus.CONFLICT, "Configure an AI provider first");
        }
    }
    private Map<String, Object> owned(String id, String user) {
        Map<String, Object> row = chats.find(id, user);
        if (row == null || row.isEmpty()) throw error(HttpStatus.NOT_FOUND, "Chat not found");
        return row;
    }
    private Map<String, Object> view(Map<String, Object> row, boolean messages) {
        Map<String, Object> out = new LinkedHashMap<>();
        GameBrief brief = brief(row);
        String state = row.get("status").toString();
        if ("replying".equals(state) && replyExpired(row)) state = "draft";
        out.put("id", row.get("id")); out.put("status", state); out.put("revision", row.get("revision"));
        out.put("createType", row.get("create_type")); out.put("projectId", row.get("project_id"));
        out.put("fundingMode", row.get("funding_mode")); out.put("voucherId", row.get("voucher_id"));
        out.put("jobId", row.get("job_id")); out.put("updatedAt", row.get("updated_at"));
        out.put("brief", brief == null ? null : brief.view()); out.put("ready", brief != null && brief.ready());
        if (messages) out.put("messages", chats.messages(row.get("id").toString()).stream().map(m -> {
            Map<String, Object> message = new LinkedHashMap<>();
            message.put("requestId", m.get("request_id"));
            message.put("role", m.get("role")); message.put("content", m.get("content"));
            try { message.put("skillIds", JSON.readValue(m.get("skill_ids_json").toString(),
                    new com.fasterxml.jackson.core.type.TypeReference<List<String>>() {})); }
            catch (Exception invalid) { throw new IllegalStateException("Invalid stored skill ids", invalid); }
            message.put("sequence", m.get("sequence_no")); return message;
        }).toList());
        return out;
    }
    private GameBrief brief(Map<String, Object> row) {
        if (row.get("brief_json") == null) return null;
        try { return GameBrief.parse(JSON.readTree(row.get("brief_json").toString())); }
        catch (Exception invalid) { throw new IllegalStateException("Invalid stored game brief", invalid); }
    }
    private boolean replyExpired(Map<String, Object> row) {
        Object expiry = row.get("reply_expires_at");
        java.time.Instant expires = expiry instanceof java.time.LocalDateTime local ? local.toInstant(java.time.ZoneOffset.UTC)
                : expiry instanceof java.sql.Timestamp timestamp ? timestamp.toInstant() : null;
        return expires != null && expires.isBefore(java.time.Instant.now());
    }
    private void rate(String user) {
        Long n = redis.execute(RATE, List.of("create:chat:rate:" + user));
        if (n == null || n > 20) throw error(HttpStatus.TOO_MANY_REQUESTS, "对话请求过于频繁，请稍后重试。");
    }
    static void uuid(String value) {
        if (value == null || !value.matches("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"))
            throw error(HttpStatus.BAD_REQUEST, "Invalid chat identifier");
    }
    private static String json(Object value) {
        try { return JSON.writeValueAsString(value); }
        catch (Exception invalid) { throw new IllegalStateException(invalid); }
    }
    private static ResponseStatusException error(HttpStatus status, String message) { return new ResponseStatusException(status, message); }
}
