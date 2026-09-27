param(
    [string]$First = "http://localhost:8080",
    [string]$Second = "http://localhost:8081"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    Write-Host "PASS $Message"
}

# Run after: docker compose -f docker-compose.yml -f docker-compose.multi-instance.yml --profile test up -d --build mysql redis rabbitmq minio mock-llm api api-replica
foreach ($api in @($First, $Second)) {
    $deadline = (Get-Date).AddMinutes(3)
    do {
        try { $health = Invoke-RestMethod "$api/health" -TimeoutSec 3 } catch { $health = $null }
        if ($health -and $health.status -eq "ok") { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Assert ($health -and $health.status -eq "ok") "API healthy at $api"
}

$email = "multi-$([guid]::NewGuid().ToString('N'))@example.test"
$password = "test-$([guid]::NewGuid().ToString('N'))"
$registration = Invoke-RestMethod -Method Post "$First/auth/register" -ContentType "application/json" -Body (
    @{ email=$email; password=$password; displayName="Multi-instance" } | ConvertTo-Json)
$token = $registration.accessToken
$headers = @{ Authorization = "Bearer $token" }
$session = Invoke-RestMethod "$Second/auth/session" -Headers $headers
Assert ($session.authenticated -eq $true) "Session created on first replica resolves on second"

$html = '<!doctype html><html><head><title>Concurrency</title></head><body><canvas id="game"></canvas><script>const score = 1; document.body.dataset.score = String(score);</script></body></html>'
$artifactBody = @{ prompt="Concurrent external artifact"; html=$html } | ConvertTo-Json -Compress
$key = "multi-$([guid]::NewGuid().ToString('N'))"
$calls = 1..8 | ForEach-Object -Parallel {
    $api = if ($_ % 2 -eq 0) { $using:First } else { $using:Second }
    $bearer = $using:token
    $artifactKey = $using:key
    try {
        Invoke-RestMethod -Method Post "$api/create/artifacts" -Headers @{
            Authorization = "Bearer $bearer"; "X-Idempotency-Key" = $artifactKey
        } -ContentType "application/json" -Body $using:artifactBody
    } catch { throw "Artifact submit failed on $api`: $($_.Exception.Message)" }
} -ThrottleLimit 8
Assert (@($calls).Count -eq 8 -and @($calls | Select-Object -ExpandProperty jobId -Unique).Count -eq 1) "Concurrent idempotent artifact calls create one job"

$projectId = $calls[0].projectId
$revisions = 1..6 | ForEach-Object -Parallel {
    $api = if ($_ % 2 -eq 0) { $using:First } else { $using:Second }
    $bearer = $using:token
    $body = @{ prompt="Revision $_"; html=$using:html; projectId=$using:projectId } | ConvertTo-Json -Compress
    Invoke-RestMethod -Method Post "$api/create/artifacts" -Headers @{
        Authorization = "Bearer $bearer"
    } -ContentType "application/json" -Body $body
} -ThrottleLimit 6
Assert (@($revisions | Select-Object -ExpandProperty versionId -Unique).Count -eq 6) "Concurrent revisions have unique versions"

$config = @{ baseUrl="http://mock-llm:8080"; model="mock-model"; apiKey="sk-mock-key"; provider="openai" } | ConvertTo-Json
Invoke-RestMethod -Method Put "$First/create/ai-config" -Headers $headers -ContentType "application/json" -Body $config | Out-Null
$jobs = 1..8 | ForEach-Object -Parallel {
    $api = if ($_ % 2 -eq 0) { $using:First } else { $using:Second }
    $bearer = $using:token
    $artifactKey = $using:key
    try {
        $job = Invoke-RestMethod -Method Post "$api/create/jobs" -Headers @{
            Authorization = "Bearer $bearer"; "X-Idempotency-Key" = "billing-$artifactKey-$_"
        } -ContentType "application/json" -Body (@{ prompt="Billing concurrency $_"; agentMode="chat"; createType="init" } | ConvertTo-Json -Compress)
        @{ accepted=$true; id=$job.id }
    } catch {
        @{ accepted=$false; status=[int]$_.Exception.Response.StatusCode }
    }
} -ThrottleLimit 8
$accepted = @($jobs | Where-Object accepted)
Write-Host "Creation responses: $($jobs | ConvertTo-Json -Compress)"
Assert ($accepted.Count -eq 8) "Parallel creation requests do not use local token balance as a gate"

$deadline = (Get-Date).AddMinutes(3)
do {
    $states = @($accepted | ForEach-Object { (Invoke-RestMethod "$Second/create/jobs/$($_.id)" -Headers $headers).status })
    if (@($states | Where-Object { $_ -notin @('completed','failed','canceled') }).Count -eq 0) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
Assert (@($states | Where-Object { $_ -notin @('completed','failed','canceled') }).Count -eq 0) "Accepted jobs reach a terminal state"

$userId = $session.user.id
$sql = "SELECT a.balance,a.reserved,COALESCE(SUM(CASE WHEN l.entry_type='GRANT' THEN l.amount WHEN l.entry_type='SETTLE' THEN -l.amount ELSE 0 END),0) FROM token_accounts a LEFT JOIN token_ledger l ON l.user_id=a.user_id WHERE a.user_id='$userId' GROUP BY a.balance,a.reserved"
$passwordForDb = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "gameweare" }
$row = docker compose -f docker-compose.yml -f docker-compose.multi-instance.yml exec -T -e "MYSQL_PWD=$passwordForDb" mysql mysql -ugameweare -N -B gameweare -e $sql
if ($LASTEXITCODE -ne 0) { throw "Ledger query failed" }
$fields = $row.Trim() -split "`t"
Assert ([long]$fields[1] -eq 0 -and [long]$fields[0] -eq [long]$fields[2]) "New generation leaves the legacy local balance unchanged"

Invoke-RestMethod -Method Post "$First/auth/logout" -Headers $headers | Out-Null
$revoked = Invoke-RestMethod "$Second/auth/session" -Headers $headers
Assert ($revoked.authenticated -eq $false) "Logout on first replica revokes session on second"
