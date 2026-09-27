# Start the local GameWeare stack with AgentScope's Docker filesystem backend.
# Each create job gets an isolated, network-disabled Docker sandbox container.
param([switch]$Mock)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $root '.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Push-Location $root
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker CLI is required' }
    if (-not (Get-Command java -ErrorAction SilentlyContinue)) { throw 'Java 17 or newer is required' }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Node.js is required for the web app' }
    if (-not (Test-Path 'apps/web/node_modules/vite/bin/vite.js')) {
        throw 'Frontend dependencies are missing; run npm install in apps/web first'
    }
    if (-not (Test-Path '.env')) {
        Set-Content -LiteralPath '.env' -Encoding utf8 -Value 'MINIO_IMAGE=ghcr.io/coollabsio/minio@sha256:69b55a1c1c5dc285ce04db96689f5b2102317fc77a50680a1874ca6efd1c87f9'
    }
    docker compose up -d mysql rabbitmq redis minio
    if ($LASTEXITCODE -ne 0) { throw 'Docker infrastructure failed to start' }
    if ($Mock) {
        docker compose --profile test up -d mock-llm
        if ($LASTEXITCODE -ne 0) { throw 'Mock model failed to start' }
    }
    try { $apiAlreadyRunning = (Invoke-RestMethod -Uri 'http://localhost:8080/health' -TimeoutSec 2).status -eq 'ok' }
    catch { $apiAlreadyRunning = $false }
    if (-not $apiAlreadyRunning) {
        docker build --progress=quiet --target build -t gameweare-backend-build:local apps/api-java
        if ($LASTEXITCODE -ne 0) { throw 'API build failed' }
        $containerId = docker create gameweare-backend-build:local
        if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the API build' }
        try {
            docker cp "${containerId}:/app/target/gameweare-backend-api-0.1.0-SNAPSHOT.jar" (Join-Path $runtime 'gameweare-backend-api.jar')
            if ($LASTEXITCODE -ne 0) { throw 'Could not extract the API jar' }
        } finally { docker rm $containerId | Out-Null }
    }

    $secretFile = Join-Path $runtime 'ai-config-secret'
    if (-not (Test-Path $secretFile)) {
        $bytes = New-Object byte[] 32
        [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        [IO.File]::WriteAllText($secretFile, [Convert]::ToBase64String($bytes))
    }
    $env:AI_CONFIG_SECRET = [IO.File]::ReadAllText($secretFile)
    $env:MYSQL_URL = 'jdbc:mysql://localhost:3307/gameweare'
    $env:RABBITMQ_PORT = '5673'
    $env:REDIS_PORT = '6380'
    $env:MINIO_ENDPOINT = 'http://localhost:9000'
    $env:AGENT_ENGINE = 'agentscope'
    $env:AGENT_FILESYSTEM = 'docker'
    $env:AGENT_DOCKER_IMAGE = 'public.ecr.aws/docker/library/python:3.12-alpine'
    $env:LLM_ALLOW_PRIVATE_ENDPOINTS = if ($Mock) { 'true' } else { 'false' }

    if (-not $apiAlreadyRunning) {
        $javaExe = (Get-Command java).Source
        $apiArgs = @{
            FilePath = $javaExe
            ArgumentList = @('-jar', (Join-Path $runtime 'gameweare-backend-api.jar'))
            WorkingDirectory = $root
            RedirectStandardOutput = (Join-Path $runtime 'api.out.log')
            RedirectStandardError = (Join-Path $runtime 'api.err.log')
            WindowStyle = 'Hidden'
            PassThru = $true
        }
        $api = Start-Process @apiArgs
        Set-Content -LiteralPath (Join-Path $runtime 'api.pid') -Value $api.Id
    }
    $deadline = (Get-Date).AddMinutes(2)
    do {
        try { $health = Invoke-RestMethod -Uri 'http://localhost:8080/health' -TimeoutSec 3 }
        catch { $health = $null }
        if ($health.status -eq 'ok') { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if ($health.status -ne 'ok') { throw 'API health check failed; inspect .runtime/api.err.log' }
    if ($IsWindows) {
        # Oracle's javapath shim can spawn a second java.exe. Save the listener PID so
        # the next restart stops the actual server rather than only the launcher.
        $listener = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($listener) { Set-Content -LiteralPath (Join-Path $runtime 'api.pid') -Value $listener.OwningProcess }
    }

    try { Invoke-WebRequest -Uri 'http://localhost:1314/' -TimeoutSec 2 -UseBasicParsing | Out-Null }
    catch {
        $nodeExe = (Get-Command node).Source
        $vite = Join-Path $root 'apps/web/node_modules/vite/bin/vite.js'
        $webArgs = @{
            FilePath = $nodeExe
            ArgumentList = @($vite, '--host', '0.0.0.0', '--port', '1314')
            WorkingDirectory = (Join-Path $root 'apps/web')
            RedirectStandardOutput = (Join-Path $runtime 'web.out.log')
            RedirectStandardError = (Join-Path $runtime 'web.err.log')
            WindowStyle = 'Hidden'
            PassThru = $true
        }
        $web = Start-Process @webArgs
        Set-Content -LiteralPath (Join-Path $runtime 'web.pid') -Value $web.Id
    }
    Write-Host 'GameWeare is ready: http://localhost:1314/'
    if ($Mock) { Write-Host 'Mock model URL: http://127.0.0.1:8090' }
} finally { Pop-Location }
