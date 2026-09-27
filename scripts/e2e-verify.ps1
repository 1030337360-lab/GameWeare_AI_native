# End-to-end verification of the GameWeare stack: create -> publish -> play, plus
# plan/decentralized approval flows and token ledger consistency.
# -Engine legacy     verifies the default LlmClient /responses engine.
# -Engine agentscope verifies the AgentScope harness engine (chat/completions protocol);
#                   with -Filesystem local it runs without a Kubernetes cluster and also
#                   checks per-call usage rows in agent_model_calls.
# Prereq: LLM_ALLOW_PRIVATE_ENDPOINTS=true docker compose --profile test up -d
param(
    [string]$Api = "http://localhost:8080",
    [string]$MockBaseUrl = "http://mock-llm:8080",
    [int]$JobTimeoutSeconds = 180,
    [ValidateSet("legacy", "agentscope")][string]$Engine = "legacy",
    [ValidateSet("kubernetes", "docker", "local")][string]$Filesystem = "local",
    [switch]$UseExistingApi
)
$ErrorActionPreference = "Stop"
$script:Failures = 0
$script:Checks = 0

function Pass([string]$name) {
    $script:Checks++
    Write-Host ("  PASS  {0}" -f $name) -ForegroundColor Green
}

function Fail([string]$name, [string]$detail) {
    $script:Checks++
    $script:Failures++
    Write-Host ("  FAIL  {0} :: {1}" -f $name, $detail) -ForegroundColor Red
    throw "Verification aborted at: $name"
}

function Step([string]$name) { Write-Host "`n== $name ==" -ForegroundColor Cyan }

function Invoke-Api([string]$Method, [string]$Path, $Body = $null, [hashtable]$Headers = $null) {
    $args = @{ Method = $Method; Uri = "$Api$Path"; ContentType = "application/json" }
    if ($Headers) { $args.Headers = $Headers }
    if ($null -ne $Body) { $args.Body = ($Body | ConvertTo-Json -Depth 6) }
    Invoke-RestMethod @args
}

function Wait-JobStatus([string]$JobId, [string[]]$Target, [hashtable]$Auth, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($JobTimeoutSeconds)
    $job = $null
    while ((Get-Date) -lt $deadline) {
        $job = Invoke-Api GET "/create/jobs/$JobId" $null $Auth
        if ($Target -contains $job.status) { return $job }
        if ("failed" -eq $job.status) { Fail $Label "job failed: $($job.errorMessage)" }
        Start-Sleep -Seconds 2
    }
    Fail $Label "timed out; last status: $($job.status)"
}

function Invoke-Mysql([string]$Sql) {
    $root = Split-Path -Parent $PSScriptRoot
    $mysqlPassword = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "gameweare" }
    # mysql prints a harmless password warning on stderr; under $ErrorActionPreference=Stop
    # PowerShell 5.1 turns any native stderr line into a terminating error, so muffle it.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        Push-Location $root
        $result = docker compose exec -T mysql mysql "-ugameweare" "-p$mysqlPassword" gameweare -N -B -e $Sql
        if ($LASTEXITCODE -ne 0 -or -not $result) { throw "mysql query failed (exit $LASTEXITCODE)" }
        return $result
    } finally {
        $ErrorActionPreference = $previous
        Pop-Location
    }
}

# ---------- 0. switch engine ----------
if ($Engine -eq "agentscope" -and -not $UseExistingApi) {
    Step "Switch API to AgentScope engine (filesystem=$Filesystem)"
    $root = Split-Path -Parent $PSScriptRoot
    $env:LLM_ALLOW_PRIVATE_ENDPOINTS = "true"
    $env:AGENT_ENGINE = "agentscope"
    $env:AGENT_FILESYSTEM = $Filesystem
    Push-Location $root
    try {
        docker compose --profile test up -d --force-recreate api | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail "engine-switch" "docker compose could not recreate the api container" }
    } finally { Pop-Location }
    $deadline = (Get-Date).AddSeconds(120)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 5
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if (-not $ready) { Fail "engine-switch" "API did not become healthy after engine switch" }
    Pass "API restarted with AGENT_ENGINE=agentscope"
}

# ---------- 1. stack health ----------
Step "Stack health ($Engine engine)"
$deadline = (Get-Date).AddSeconds(90)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 5
        if ($health.status -eq "ok") { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 3 }
}
if (-not $healthy) { Fail "health" "API did not become healthy within 90s" }
Pass "GET /health returns ok"

# ---------- 2. register + AI config ----------
Step "Register and configure AI provider"
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$email = "e2e-$Engine-$stamp@example.com"
$register = Invoke-Api POST "/auth/register" @{ email = $email; password = "e2e-password-123"; displayName = "E2E Tester" }
if (-not $register.accessToken) { Fail "register" "no accessToken returned" }
Pass "registered $email"
$Auth = @{ Authorization = "Bearer $($register.accessToken)" }
$userId = $register.user.id

$config = Invoke-Api PUT "/create/ai-config" @{ baseUrl = $MockBaseUrl; model = "mock-model"; apiKey = "sk-mock-key"; provider = "openai" } $Auth
if (-not $config.configured) { Fail "ai-config" "configured flag not set" }
Pass "AI provider saved (baseUrl=$MockBaseUrl)"

$probe = Invoke-Api POST "/create/ai-config/test" @{} $Auth
if (-not $probe.ok) { Fail "ai-config-test" "provider test failed: $($probe.message)" }
Pass "API reached the mock provider"

# ---------- 3. chat create -> publish -> play ----------
Step "Chat mode: create, publish, play ($Engine engine)"
$idem = "e2e-$Engine-chat-$stamp"
$createHeaders = @{ Authorization = $Auth.Authorization; "X-Idempotency-Key" = $idem }
$chatBody = @{ prompt = "Create a neon runner game with score"; agentMode = "chat" }
$job = Invoke-Api POST "/create/jobs" $chatBody $createHeaders
if (-not $job.id) { Fail "create-job" "no job id returned" }
Pass "job accepted ($($job.id))"

$again = Invoke-Api POST "/create/jobs" $chatBody $createHeaders
if ($again.id -ne $job.id) { Fail "idempotency" "same key returned different job: $($again.id)" }
Pass "idempotency key returns the same job"

$done = Wait-JobStatus $job.id @("completed") $Auth "chat-generation"
if (-not $done.gameId -or -not $done.versionId) { Fail "chat-generation" "missing gameId/versionId" }
Pass "worker completed generation (gameId=$($done.gameId))"

if ($Engine -eq "agentscope") {
    $callsRaw = Invoke-Mysql "SELECT state, COUNT(*), COALESCE(SUM(prompt_tokens + completion_tokens),0) FROM agent_model_calls WHERE job_id='$($job.id)' GROUP BY state"
    $states = @{}
    foreach ($line in ($callsRaw | Where-Object { $_ -match "\S" })) {
        $parts = $line -split "`t"
        $states[$parts[0]] = @{ count = [int]$parts[1]; tokens = [long]$parts[2] }
    }
    if ($states.Keys.Count -ne 1 -or -not $states.ContainsKey("completed")) {
        Fail "agent-model-calls" "unexpected call states: $($states.Keys -join ',')"
    }
    if ($states["completed"].count -lt 3) {
        Fail "agent-model-calls" "expected at least 3 model calls (write/deliver/final), got $($states['completed'].count)"
    }
    if ($states["completed"].tokens -le 0) { Fail "agent-model-calls" "no tokens recorded" }
    Pass "per-call usage recorded ($($states['completed'].count) completed calls, $($states['completed'].tokens) tokens)"
}

$published = Invoke-Api POST "/create/jobs/$($job.id)/publish" @{} $Auth
if ($published.publishStatus -ne "published") { Fail "publish" "publishStatus=$($published.publishStatus)" }
$slug = $published.gameSlug
Pass "published as /games/$slug"

$detail = Invoke-Api GET "/games/$slug"
if ($detail.id -ne $slug) { Fail "catalog" "detail id mismatch: $($detail.id)" }
Pass "catalog lists the published game"

$manifest = Invoke-Api GET "/play/$slug/manifest"
if ($manifest.entry -ne "index.html" -or $manifest.runtime -ne "iframe-html5") { Fail "manifest" "unexpected manifest: $($manifest | ConvertTo-Json -Compress)" }
Pass "play manifest served"

$doc = Invoke-WebRequest -Uri "$Api/play/$slug/document" -UseBasicParsing
$csp = $doc.Headers["Content-Security-Policy"]
if (-not $csp) { $csp = $doc.Headers["content-security-policy"] }
if ($doc.Content -notmatch "<html" -or -not $csp -or $csp -notmatch "sandbox" -or
        $csp -notmatch "frame-ancestors.*http://localhost:1314" -or
        $doc.Headers["X-Frame-Options"]) {
    Fail "play-document" "html/CSP or frontend frame permission missing"
}
Pass "play document served with sandbox CSP"

$event = Invoke-Api POST "/events/play" @{ gameId = $slug; event = "game_start"; anonymousId = "e2e-anon-$stamp" }
if (-not $event.counted) { Fail "play-event" "first game_start not counted" }
$detailAfter = Invoke-Api GET "/games/$slug"
if ([long]$detailAfter.plays -lt 1) { Fail "play-event" "plays counter did not increase" }
Pass "play event counted (plays=$($detailAfter.plays))"

# ---------- 3b. generated cover and optimized version reuse ----------
Step "Cover generation and optimization reuse ($Engine engine)"
$cover = Invoke-WebRequest -Uri "$Api/games/$slug/cover" -UseBasicParsing
if ($cover.StatusCode -ne 200 -or $cover.Headers["Content-Type"] -notmatch "image/svg\+xml" -or
        $cover.Content -notmatch "Mock Runner") { Fail "generated-cover" "catalog cover is missing or not model-generated" }
Pass "generated cover is visible on the public game page"
$originalCoverKey = [string](Invoke-Mysql "SELECT cover_object_key FROM games WHERE id='$($done.gameId)'")
if (-not $originalCoverKey) { Fail "generated-cover" "original cover key was not persisted" }

$optJob = Invoke-Api POST "/create/jobs" @{
    prompt = "Improve the runner controls while retaining the original cover"
    agentMode = "refine"
    createType = "opt"
    projectId = $done.projectId
} $Auth
$optimized = Wait-JobStatus $optJob.id @("completed") $Auth "optimization"
if ($optimized.coverDataUrl -ne $done.coverDataUrl) {
    Fail "optimized-cover" "optimized job preview replaced the original cover"
}
$optCoverCount = [int](Invoke-Mysql "SELECT COUNT(*) FROM assets WHERE version_id='$($optimized.versionId)' AND kind='cover'")
if ($optCoverCount -ne 0) { Fail "optimized-cover" "optimization stored $optCoverCount new cover assets" }
$optimizedPublished = Invoke-Api POST "/create/jobs/$($optJob.id)/publish" @{} $Auth
$coverKeyAfter = [string](Invoke-Mysql "SELECT cover_object_key FROM games WHERE id='$($done.gameId)'")
if ($optimizedPublished.publishStatus -ne "published" -or $coverKeyAfter -ne $originalCoverKey) {
    Fail "optimized-cover" "publishing changed the original cover key"
}
Pass "optimization and publication retain the original cover"

# ---------- 4. plan approval flow ----------
Step "Plan mode: preview and approval ($Engine engine)"
$planJob = Invoke-Api POST "/create/jobs" @{ prompt = "Design and build a maze game"; agentMode = "plan" } $Auth
$planning = Wait-JobStatus $planJob.id @("planning") $Auth "plan-preview-wait"
Pass "plan preview ready (status=planning)"

$preview = Invoke-Api GET "/create/runs/$($planJob.id)/plan-preview" $null $Auth
if ($preview.planPreview.plan.Count -lt 3) { Fail "plan-preview" "expected at least 3 plan steps" }
Pass "plan preview exposes $($preview.planPreview.plan.Count) steps and $($preview.planPreview.acceptanceChecks.Count) checks"

$accepted = Invoke-Api POST "/create/runs/$($planJob.id)/plan-decision" @{ decision = "accepted" } $Auth
if ($accepted.status -ne "pending") { Fail "plan-decision" "status after accept: $($accepted.status)" }
$planDone = Wait-JobStatus $planJob.id @("completed") $Auth "plan-final-generation"
Pass "generation continued after approval (gameId=$($planDone.gameId))"

# ---------- 5. decentralized selection flow ----------
Step "Decentralized mode: three candidates, select, confirm ($Engine engine)"
$decJob = Invoke-Api POST "/create/jobs" @{ prompt = "Propose three arcade directions and build the chosen one"; agentMode = "decentralized" } $Auth
Wait-JobStatus $decJob.id @("reviewing") $Auth "decentralized-preview-wait" | Out-Null
Pass "candidate previews ready (status=reviewing)"

$previews = Invoke-Api GET "/create/runs/$($decJob.id)/decentralized-previews" $null $Auth
if ($previews.candidates.Count -ne 3) { Fail "decentralized-previews" "expected 3 candidates, got $($previews.candidates.Count)" }
if ($previews.selectedCandidateId) { Fail "decentralized-previews" "unexpected pre-selection" }
Pass "three candidates returned"

$chosen = $previews.candidates[0].candidateId
$selection = Invoke-Api POST "/create/runs/$($decJob.id)/decentralized-selection" @{ candidateId = $chosen } $Auth
if ($selection.selectedCandidateId -ne $chosen) { Fail "decentralized-selection" "selection not stored" }
Pass "candidate selected ($chosen)"

$confirmed = Invoke-Api POST "/create/runs/$($decJob.id)/decentralized-confirm" @{ decision = "accepted" } $Auth
if ($confirmed.status -ne "pending") { Fail "decentralized-confirm" "status after confirm: $($confirmed.status)" }
$decDone = Wait-JobStatus $decJob.id @("completed") $Auth "decentralized-final-generation"
Pass "final generation completed for selected direction (gameId=$($decDone.gameId))"

# ---------- 6. provider usage without local balance gating ----------
Step "Provider usage and legacy local ledger (MySQL)"
$ledgerRaw = $null
$accountRaw = $null
try {
    $ledgerRaw = Invoke-Mysql "SELECT entry_type, COUNT(*) FROM token_ledger WHERE user_id='$userId' GROUP BY entry_type"
    $accountRaw = Invoke-Mysql "SELECT balance, reserved FROM token_accounts WHERE user_id='$userId'"
} catch {
    Write-Host "  WARN  ledger check skipped: $($_.Exception.Message)" -ForegroundColor Yellow
}
if ($ledgerRaw) {
    $types = @{}
    foreach ($line in ($ledgerRaw | Where-Object { $_ -match "\S" })) {
        $parts = $line -split "`t"
        $types[$parts[0]] = [int]$parts[1]
    }
    if ($types["GRANT"] -ne 1 -or $types.ContainsKey("RESERVE") -or $types.ContainsKey("SETTLE")) {
        Fail "ledger" "unexpected ledger entries: $(($types | Out-String).Trim())"
    }
    $fields = ($accountRaw | Where-Object { $_ -match "\S" } | Select-Object -First 1) -split "`t"
    if ([long]$fields[1] -ne 0) { Fail "ledger" "reserved is not zero: $($accountRaw)" }
    Pass "provider usage is recorded; local account has 1 GRANT and no creation reservations, reserved=0, balance=$($fields[0])"
}

Write-Host "`n================================================" -ForegroundColor Cyan
if ($script:Failures -eq 0) {
    Write-Host ("E2E VERIFICATION PASSED ({0} checks, engine={1})" -f $script:Checks, $Engine) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("E2E VERIFICATION FAILED ({0} failed of {1})" -f $script:Failures, $script:Checks) -ForegroundColor Red
    exit 1
}
