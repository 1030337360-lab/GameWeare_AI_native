package com.gameweare.api.create;

import io.agentscope.core.agent.RuntimeContext;
import io.agentscope.harness.agent.sandbox.ExecResult;
import io.agentscope.harness.agent.sandbox.Sandbox;
import io.agentscope.harness.agent.sandbox.SandboxState;
import io.agentscope.harness.agent.sandbox.WorkspaceSpec;
import io.agentscope.harness.agent.sandbox.impl.docker.DockerSandbox;
import io.agentscope.harness.agent.sandbox.impl.docker.DockerSandboxClient;
import io.agentscope.harness.agent.sandbox.impl.docker.DockerSandboxClientOptions;
import io.agentscope.harness.agent.sandbox.impl.docker.DockerSandboxState;
import io.agentscope.harness.agent.sandbox.snapshot.SandboxSnapshotSpec;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/** Preserves shell command bytes when the Docker CLI is launched from Windows. */
final class WindowsDockerSandboxClient extends DockerSandboxClient {
    @Override
    public Sandbox create(WorkspaceSpec workspaceSpec, SandboxSnapshotSpec snapshotSpec,
            DockerSandboxClientOptions options) {
        return new QuotedCommandSandbox((DockerSandboxState)
                super.create(workspaceSpec, snapshotSpec, options).getState());
    }

    @Override
    public Sandbox resume(SandboxState state) {
        if (!(state instanceof DockerSandboxState dockerState))
            throw new IllegalArgumentException("Expected Docker sandbox state");
        return new QuotedCommandSandbox(dockerState);
    }

    private static final class QuotedCommandSandbox extends DockerSandbox {
        private QuotedCommandSandbox(DockerSandboxState state) { super(state); }

        @Override
        protected ExecResult doExec(RuntimeContext context, String command, int timeoutSeconds)
                throws Exception {
            // AgentScope 2.0.3's edit_file builds a python3 -c script with literal
            // backslash-n separators. Python requires real newlines in that script.
            String executable = command.startsWith("python3 -c \"")
                    ? command.replace("\\n", "\n") : command;
            String encoded = Base64.getEncoder().encodeToString(executable.getBytes(StandardCharsets.UTF_8));
            return super.doExec(context, "echo " + encoded + " | base64 -d | sh", timeoutSeconds);
        }
    }
}
