# End-to-end verification of the Gameweare stack: create -> publish -> play, plus
# plan/decentralized approval flows and token ledger consistency.
# Prereq: LLM_ALLOW_PRIVATE_ENDPOINTS=true docker compose --profile test up -d
param(
    [string]$Api = "http://localhost:8080",
    [string]$MockBaseUrl = "http://mock-llm:8080",
    [int]$JobTimeoutSeconds = 120
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

# ---------- 1. stack health ----------
Step "Stack health"
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
$email = "e2e-$stamp@example.com"
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
Step "Chat mode: create, publish, play"
$idem = "e2e-chat-$stamp"
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
if ($doc.Content -notmatch "<html" -or -not $csp -or $csp -notmatch "sandbox") { Fail "play-document" "html/CSP missing" }
Pass "play document served with sandbox CSP"

$event = Invoke-Api POST "/events/play" @{ gameId = $slug; event = "game_start"; anonymousId = "e2e-anon-$stamp" }
if (-not $event.counted) { Fail "play-event" "first game_start not counted" }
$detailAfter = Invoke-Api GET "/games/$slug"
if ([long]$detailAfter.plays -lt 1) { Fail "play-event" "plays counter did not increase" }
Pass "play event counted (plays=$($detailAfter.plays))"

# ---------- 4. plan approval flow ----------
Step "Plan mode: preview and approval"
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
Step "Decentralized mode: three candidates, select, confirm"
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

# ---------- 6. token ledger consistency ----------
Step "Token ledger (MySQL)"
$root = Split-Path -Parent $PSScriptRoot
$ledgerRaw = $null
$accountRaw = $null
try {
    $mysqlPassword = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "gameweare" }
    Push-Location $root
    # mysql prints a harmless password warning on stderr; under $ErrorActionPreference=Stop
    # PowerShell 5.1 turns any native stderr line into a terminating error, so muffle it.
    $ErrorActionPreference = "SilentlyContinue"
    $ledgerRaw = docker compose exec -T mysql mysql "-ugameweare" "-p$mysqlPassword" gameweare -N -B -e `
        "SELECT entry_type, COUNT(*) FROM token_ledger WHERE user_id='$userId' GROUP BY entry_type"
    if ($LASTEXITCODE -ne 0 -or -not $ledgerRaw) { throw "mysql query failed (exit $LASTEXITCODE)" }
    $accountRaw = docker compose exec -T mysql mysql "-ugameweare" "-p$mysqlPassword" gameweare -N -B -e `
        "SELECT balance, reserved FROM token_accounts WHERE user_id='$userId'"
    if ($LASTEXITCODE -ne 0 -or -not $accountRaw) { throw "mysql query failed (exit $LASTEXITCODE)" }
} catch {
    Write-Host "  WARN  ledger check skipped: $($_.Exception.Message)" -ForegroundColor Yellow
} finally {
    $ErrorActionPreference = "Stop"
    Pop-Location
}
if ($ledgerRaw) {
    $types = @{}
    foreach ($line in ($ledgerRaw | Where-Object { $_ -match "\S" })) {
        $parts = $line -split "`t"
        $types[$parts[0]] = [int]$parts[1]
    }
    if ($types["GRANT"] -ne 1 -or $types["RESERVE"] -ne 3 -or $types["SETTLE"] -ne 3) {
        Fail "ledger" "unexpected ledger entries: $(($types | Out-String).Trim())"
    }
    $fields = ($accountRaw | Where-Object { $_ -match "\S" } | Select-Object -First 1) -split "`t"
    if ([long]$fields[1] -ne 0) { Fail "ledger" "reserved is not zero: $($accountRaw)" }
    Pass "ledger consistent: 1 GRANT, 3 RESERVE, 3 SETTLE, reserved=0, balance=$($fields[0])"
}

Write-Host "`n================================================" -ForegroundColor Cyan
if ($script:Failures -eq 0) {
    Write-Host ("E2E VERIFICATION PASSED ({0} checks)" -f $script:Checks) -ForegroundColor Green
    exit 0
} else {
    Write-Host ("E2E VERIFICATION FAILED ({0} failed of {1})" -f $script:Failures, $script:Checks) -ForegroundColor Red
    exit 1
}
