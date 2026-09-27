# Focused CI smoke test. The full mock-provider workflow remains in e2e-verify.ps1.
param([string]$Api = "http://localhost:8080")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    Write-Host "PASS $Message"
}

$deadline = (Get-Date).AddSeconds(120)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 5
        if ($health.status -eq "ok") { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
Assert $healthy "API health"

# Flyway migration must have completed before the API accepts requests.
$dbPassword = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "gameweare" }
$migrationCount = docker compose exec -T -e "MYSQL_PWD=$dbPassword" mysql mysql -ugameweare -N -B gameweare -e `
    "SELECT COUNT(*) FROM flyway_schema_history WHERE success=1"
if ($LASTEXITCODE -ne 0) { throw "Flyway query failed with exit code $LASTEXITCODE" }
Assert ([int]$migrationCount -ge 4) "Flyway migrations applied"

$email = "ci-$([guid]::NewGuid().ToString('N'))@example.test"
$password = "ci-password-$([guid]::NewGuid().ToString('N'))"
$body = @{ email = $email; password = $password; displayName = "CI user" } | ConvertTo-Json
$registered = Invoke-RestMethod -Method Post -Uri "$Api/auth/register" -ContentType "application/json" -Body $body
Assert (-not [string]::IsNullOrWhiteSpace($registered.accessToken)) "Registration returns a bearer token"
$headers = @{ Authorization = "Bearer $($registered.accessToken)" }

$session = Invoke-RestMethod -Uri "$Api/auth/session" -Headers $headers
Assert ($session.authenticated -eq $true -and $session.user.email -eq $email) "Registered session resolves"

$loginBody = @{ email = $email; password = $password } | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "$Api/auth/login" -ContentType "application/json" -Body $loginBody
Assert (-not [string]::IsNullOrWhiteSpace($login.accessToken)) "Login returns a bearer token"

$checkin = Invoke-RestMethod -Method Post -Uri "$Api/checkins" -Headers $headers
$repeatCheckin = Invoke-RestMethod -Method Post -Uri "$Api/checkins" -Headers $headers
Assert ($checkin.currentStreak -eq 1 -and $repeatCheckin.totalDays -eq 1) "Daily check-in is idempotent"
$wallet = Invoke-RestMethod -Uri "$Api/vouchers/me" -Headers $headers
Assert (@($wallet | Where-Object { $null -ne $_ }).Count -eq 0) "New account starts with an empty voucher wallet"
$campaignsResponse = Invoke-WebRequest -Uri "$Api/voucher-campaigns" -Headers $headers
Assert ($campaignsResponse.StatusCode -eq 200) "Voucher campaigns endpoint responds"
$trendingResponse = Invoke-WebRequest -Uri "$Api/games/trending" -Headers $headers
Assert ($trendingResponse.StatusCode -eq 200) "Trending games endpoint responds"

# The validator is the integration boundary for an external generation agent.
$validHtml = '<!doctype html><html><head><title>CI</title></head><body><canvas id="game"></canvas><script>const score = 1; document.body.dataset.score = String(score);</script></body></html>'
$valid = Invoke-RestMethod -Method Post -Uri "$Api/create/artifacts/validate" -Headers $headers `
    -ContentType "application/json" -Body (@{ html = $validHtml } | ConvertTo-Json)
Assert ($valid.ok -eq $true) "Valid HTML/JavaScript passes artifact validation"

$invalidHtml = '<!doctype html><html><body><script>const = ;</script></body></html>'
$invalid = Invoke-RestMethod -Method Post -Uri "$Api/create/artifacts/validate" -Headers $headers `
    -ContentType "application/json" -Body (@{ html = $invalidHtml } | ConvertTo-Json)
Assert ($invalid.ok -eq $false -and @($invalid.diagnostics).Count -gt 0) "Invalid JavaScript returns diagnostics"

$artifactKey = "ci-artifact-$([guid]::NewGuid().ToString('N'))"
$artifactHeaders = @{ Authorization = "Bearer $($registered.accessToken)"; "X-Idempotency-Key" = $artifactKey }
$artifactBody = @{ prompt = "CI supplied game"; html = $validHtml } | ConvertTo-Json
$artifact = Invoke-RestMethod -Method Post -Uri "$Api/create/artifacts" -Headers $artifactHeaders `
    -ContentType "application/json" -Body $artifactBody
Assert (-not [string]::IsNullOrWhiteSpace($artifact.gameId) -and `
    -not [string]::IsNullOrWhiteSpace($artifact.versionId)) "Valid artifact persists as a draft"
$repeat = Invoke-RestMethod -Method Post -Uri "$Api/create/artifacts" -Headers $artifactHeaders `
    -ContentType "application/json" -Body $artifactBody
Assert ($repeat.jobId -eq $artifact.jobId) "Artifact receipt is idempotent"
try {
    Invoke-RestMethod -Method Post -Uri "$Api/create/jobs/$($artifact.jobId)/publish" -Headers $headers | Out-Null
    throw "Unreviewed external artifact was published"
} catch {
    if (-not $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne 409) { throw }
}
Write-Host "PASS Unreviewed external artifact cannot publish"

$logout = Invoke-RestMethod -Method Post -Uri "$Api/auth/logout" -Headers $headers
$revoked = Invoke-RestMethod -Uri "$Api/auth/session" -Headers $headers
Assert ($revoked.authenticated -eq $false) "Logout revokes session"
