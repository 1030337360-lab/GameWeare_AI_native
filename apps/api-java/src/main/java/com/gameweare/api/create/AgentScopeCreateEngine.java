package com.gameweare.api.create;

import io.agentscope.core.agent.Agent;
import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.core.event.AgentEvent;
import io.agentscope.core.middleware.MiddlewareBase;
import io.agentscope.core.middleware.ActingInput;
import io.agentscope.core.tool.Toolkit;
import io.agentscope.core.message.Base64Source;
import io.agentscope.core.message.ContentBlock;
import io.agentscope.core.message.ImageBlock;
import io.agentscope.core.message.TextBlock;
import io.agentscope.core.message.UserMessage;
import io.agentscope.extensions.model.openai.OpenAIChatModel;
import io.agentscope.extensions.mysql.MysqlDistributedStore;
import io.agentscope.extensions.sandbox.kubernetes.KubernetesFilesystemSpec;
import io.agentscope.harness.agent.HarnessAgent;
import io.agentscope.harness.agent.IsolationScope;
import io.agentscope.harness.agent.artifact.ArtifactDeliveryResult;
import io.agentscope.harness.agent.filesystem.spec.LocalFilesystemSpec;
import io.agentscope.harness.agent.sandbox.impl.docker.DockerFilesystemSpec;
import io.agentscope.harness.agent.subagent.SubagentDeclaration;
import io.agentscope.harness.agent.subagent.WorkspaceMode;
import io.agentscope.harness.agent.tool.AgentSpawnTool;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.List;
import java.util.Objects;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Function;
import javax.sql.DataSource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.jdbc.core.JdbcTemplate;
import reactor.core.publisher.Flux;

/** A single create job is one AgentScope session and one isolated sandbox slot. */
@Component
final class AgentScopeCreateEngine {
    private final DataSource dataSource;
    private final JdbcTemplate db;
    private final AgentModelGateway gateway;
    private final ArtifactValidator artifactValidator;
    private final String namespace;
    private final String warmPool;
    private final String filesystemMode;
    private final String dockerImage;

    AgentScopeCreateEngine(DataSource dataSource, AgentModelGateway gateway,
            ArtifactValidator artifactValidator,
            @Value("${gameweare.agent.kubernetes.namespace:create-runners}") String namespace,
            @Value("${gameweare.agent.kubernetes.warm-pool:gameweare-create}") String warmPool,
            @Value("${gameweare.agent.filesystem:kubernetes}") String filesystem,
            @Value("${gameweare.agent.docker.image:public.ecr.aws/docker/library/python:3.12-alpine}") String dockerImage) {
        this.dataSource = dataSource;
        this.db = new JdbcTemplate(dataSource);
        this.gateway = gateway;
        this.artifactValidator = artifactValidator;
        this.namespace = namespace;
        this.warmPool = warmPool;
        if (!Set.of("kubernetes", "docker", "local").contains(filesystem))
            throw new IllegalArgumentException("gameweare.agent.filesystem must be kubernetes, docker or local");
        // Local runs model-commanded file operations inside the API container instead of a
        // Kubernetes sandbox; it exists only for offline mock tests and is rejected in production.
        this.filesystemMode = filesystem;
        this.dockerImage = dockerImage;
    }

    LlmClient.Result run(String jobId, String userId, String mode, String prompt,
            Map<String, Object> config, String apiKey, List<LlmClient.Image> images,
            boolean preview) throws Exception {
        Path workspace = Files.createTempDirectory("gameweare-agent-");
        AgentModelUsageMeter meter = new AgentModelUsageMeter(db, jobId, (String) config.get("model"));
        DelegationMeter delegation = new DelegationMeter();
        AtomicReference<byte[]> delivered = new AtomicReference<>();
        AtomicReference<String> deliveryFailure = new AtomicReference<>();
        GameValidationTool validationTool = new GameValidationTool(jobId, artifactValidator);
        try (var registration = gateway.register((String) config.get("base_url"), apiKey)) {
            var model = OpenAIChatModel.builder().apiKey(registration.token())
                    .modelName((String) config.get("model")).baseUrl(registration.baseUrl())
                    .stream(false).nativeStructuredOutputWithTools(false).build();
            Toolkit toolkit = new Toolkit();
            if (!preview) toolkit.registerTool(validationTool);
            var builder = HarnessAgent.builder().name("gameweare-create")
                    .agentId("create-" + jobId).model(model).workspace(workspace)
                    .toolkit(toolkit).enableTaskList(true)
                    .distributedStore(MysqlDistributedStore.create(dataSource))
                    .maxIters(Integer.MAX_VALUE)
                    .middleware(meter)
                    .middleware(delegation)
                    .sysPrompt(systemPrompt(mode, preview));
            if ("local".equals(filesystemMode))
                builder.filesystem(new LocalFilesystemSpec().isolationScope(IsolationScope.SESSION)
                        .project(workspace).executeTimeoutSeconds(30).maxOutputBytes(1_000_000));
            else if ("docker".equals(filesystemMode)) {
                DockerFilesystemSpec docker = new DockerFilesystemSpec().image(dockerImage)
                        .workspaceRoot("/workspace").network("none")
                        .memorySizeBytes(256L * 1024 * 1024).cpuCount(1L)
                        .additionalRunArgs("--read-only", "--tmpfs=/workspace:rw,size=64m",
                                "--tmpfs=/tmp:rw,size=32m", "--cap-drop=ALL",
                                "--security-opt=no-new-privileges", "--pids-limit=64");
                if (System.getProperty("os.name").toLowerCase(java.util.Locale.ROOT).contains("win"))
                    docker.client(new WindowsDockerSandboxClient());
                builder.filesystem(docker.isolationScope(IsolationScope.SESSION));
            }
            else
                builder.filesystem(new KubernetesFilesystemSpec().namespace(namespace)
                        .warmPoolName(warmPool).workspaceRoot("/workspace")
                        .fileApiBaseDir("/workspace").isolationScope(IsolationScope.SESSION));
            if (!preview) {
                builder.artifactDeliveryTarget((ctx, request) -> {
                    if (ctx == null || !jobId.equals(ctx.getSessionId())
                            || !"index.html".equals(request.fileName())) {
                        deliveryFailure.set("Artifact session or file name does not match this job's index.html.");
                        return ArtifactDeliveryResult.fail("Artifact does not belong to this job");
                    }
                    byte[] content = request.content();
                    if (content == null || content.length > 2_000_000) {
                        deliveryFailure.set(content == null ? "Artifact content is missing."
                                : "Artifact is " + content.length + " bytes; maximum is 2,000,000 bytes.");
                        return ArtifactDeliveryResult.fail("Artifact exceeds the 2 MB limit");
                    }
                    if (!validationTool.matchesValidatedContent(content)) {
                        deliveryFailure.set("Delivered bytes differ from the last PASS, or validate_game_html "
                                + "has not passed for the current index.html.");
                        return ArtifactDeliveryResult.fail("Call validate_game_html on the current index.html "
                                + "and fix all errors before delivery");
                    }
                    if (!delivered.compareAndSet(null, content))
                        return ArtifactDeliveryResult.conflict("index.html was already delivered");
                    return ArtifactDeliveryResult.success();
                });
            }
            if ("decentralized".equals(mode)) {
                for (int n = 1; n <= 3; n++) {
                    builder.subagent(SubagentDeclaration.builder()
                            .name("concept-" + n)
                            .description("Independent game concept designer number " + n)
                            .inlineAgentsBody("Design one distinct playable HTML5 game concept. "
                                    + "Return candidateId, title, conceptSummary, expertRole, "
                                    + "expertDomain, expertIntro, styleTags and staticHtml. "
                                    + "Do not write or publish the final game.")
                            .workspaceMode(WorkspaceMode.SHARED)
                            .persistSession(true).steps(Integer.MAX_VALUE).build());
                }
            } else if ("plan".equals(mode)) {
                builder.subagent(SubagentDeclaration.builder().name("planner")
                        .description("Plans implementation steps and acceptance checks")
                        .inlineAgentsBody("Return a concrete game plan, risks, and acceptance checks. "
                                + "Do not implement the game or approve the plan.")
                        .workspaceMode(WorkspaceMode.SHARED)
                        .persistSession(true).steps(Integer.MAX_VALUE).build());
            }
            RuntimeContext context = RuntimeContext.builder().userId(userId).sessionId(jobId)
                    .put(AgentSpawnTool.CTX_FORCE_SYNC, true)
                    .put(AgentSpawnTool.CTX_FORCE_SYNC_TIMEOUT_SECONDS, 180).build();
            String response;
            try (HarnessAgent agent = builder.build()) {
                var message = UserMessage.builder().content(messageContent(prompt, images)).build();
                var reply = agent.call(message, context).block();
                response = reply == null ? "" : reply.getTextContent();
                if (!preview && delivered.get() == null) {
                    var reminder = UserMessage.builder().textContent("index.html has not been delivered. "
                            + "Finish the current todo list, call validate_game_html on index.html, "
                            + "fix any reported errors, then call deliver_artifact. "
                            + "Do not stop with a text-only answer.").build();
                    reply = agent.call(reminder, context).block();
                    response = reply == null ? "" : reply.getTextContent();
                }
            }
            if (preview && "plan".equals(mode) && !delegation.spawned.contains("planner"))
                throw new IllegalStateException("Planner was not dispatched with agent_spawn");
            if (preview && "decentralized".equals(mode)
                    && !delegation.spawned.containsAll(Set.of("concept-1", "concept-2", "concept-3")))
                throw new IllegalStateException("Three concept agents were not dispatched with agent_spawn");
            if (preview) {
                if (meter.calls() == 0 || meter.unknownCalls() > 0 || meter.total() <= 0)
                    throw new IllegalStateException("AI provider usage is unavailable: calls=" + meter.calls()
                            + ", unknownCalls=" + meter.unknownCalls() + ", totalTokens=" + meter.total());
                return new LlmClient.Result(response, meter.input(), meter.output(), meter.total());
            }
            byte[] artifact = delivered.get();
            if (artifact == null) {
                String validationFailure = validationTool.lastFailure();
                throw new IllegalStateException(validationFailure == null
                        ? "Agent stopped without delivering index.html. "
                            + (deliveryFailure.get() == null
                                    ? "No failed validation or delivery call was recorded; check whether it wrote "
                                        + "index.html, called validate_game_html, and then called deliver_artifact."
                                    : "Last delivery failure: " + deliveryFailure.get())
                        : "Agent stopped without delivering index.html. Last validation result: " + validationFailure);
            }
            if (meter.calls() == 0 || meter.unknownCalls() > 0 || meter.total() <= 0)
                throw new IllegalStateException("AI provider usage is unavailable after artifact delivery: calls="
                        + meter.calls() + ", unknownCalls=" + meter.unknownCalls()
                        + ", totalTokens=" + meter.total());
            return new LlmClient.Result(new String(artifact, java.nio.charset.StandardCharsets.UTF_8),
                    meter.input(), meter.output(), meter.total());
        } finally {
            try (var paths = Files.walk(workspace)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList())
                    Files.deleteIfExists(path);
            }
        }
    }

    private static List<ContentBlock> messageContent(String prompt, List<LlmClient.Image> images) {
        List<ContentBlock> blocks = new ArrayList<>();
        blocks.add(TextBlock.builder().text(prompt).build());
        for (LlmClient.Image image : images) {
            String dataUrl = image.dataUrl();
            int separator = dataUrl.indexOf(";base64,");
            if (!dataUrl.startsWith("data:image/") || separator < 0)
                throw new IllegalArgumentException("Image input must be a base64 image data URL");
            String mediaType = dataUrl.substring(5, separator);
            String data = dataUrl.substring(separator + 8);
            blocks.add(ImageBlock.builder().source(new Base64Source(mediaType, data)).build());
        }
        return blocks;
    }

    private static String systemPrompt(String mode, boolean preview) {
        String common = "You create a self-contained single-file HTML5 browser game. "
                + "Never use external scripts, assets, network calls or package installs. "
                + "The application controls approval, billing, validation and publication. "
                + "Use todo_write to track the required steps and update their status as work progresses.";
        if (preview && "plan".equals(mode))
            return common + " Delegate planning with agent_spawn to planner and, if needed, "
                    + "refine by agent_send. Return ONLY JSON with plan (3-8 objects: "
                    + "id,title,goal,toolFamily,expectedOutput,acceptanceCheckRefs), "
                    + "risks (nonempty strings), acceptanceChecks (id,description,type,severity).";
        if (preview && "decentralized".equals(mode))
            return common + " Delegate three distinct concepts using agent_spawn to concept-1, "
                    + "concept-2 and concept-3. Use agent_send for any clarification. "
                    + "Return ONLY JSON with candidates: exactly three objects containing "
                    + "candidateId,title,conceptSummary,expertRole,expertDomain,expertIntro,"
                    + "styleTags (array),staticHtml (self-contained preview).";
        return common + " Keep index.html under 12 KB and finish tool arguments in one response. "
                + "Use the sandbox write_file tool to create index.html. "
                + "Then call validate_game_html with filePath=index.html. If it returns FAIL, "
                + "fix the file and validate again. Only after PASS, call deliver_artifact "
                + "with filePath=index.html and fileName=index.html. "
                + "Never give a final answer before the validated file has been delivered. "
                + "The game must contain inline CSS and JavaScript and be playable. "
                + "On the first page load, a visible Start button or playable controls must be present; "
                + "never hide both the start screen and the game before any user action. "
                + ("refine".equals(mode) ? "Preserve working features from the previous version. " : "")
                + ("react".equals(mode) ? "Use reason, tool, observe iterations and verify the file. " : "");
    }

    private static final class DelegationMeter implements MiddlewareBase {
        private final Set<String> spawned = ConcurrentHashMap.newKeySet();

        @Override
        public Flux<AgentEvent> onActing(Agent agent, RuntimeContext ctx,
                ActingInput input, Function<ActingInput, Flux<AgentEvent>> next) {
            input.toolCalls().stream().filter(tool -> "agent_spawn".equals(tool.getName()))
                    .map(tool -> spawnTarget(tool.getInput()))
                    .filter(Objects::nonNull)
                    .forEach(spawned::add);
            return next.apply(input);
        }

        /** AgentScope 2.0.3 exposes the spawn target as agentId; agent_id is kept for safety. */
        private static String spawnTarget(Map<String, Object> input) {
            Object target = input.get("agentId");
            if (target == null) target = input.get("agent_id");
            return target instanceof String id ? id : null;
        }
    }
}
