param(
    [string]$Api = "http://localhost:8080",
    [string]$ApiReplica = "http://localhost:8081",
    [int]$Requests = 80,
    [switch]$VerifyRedemption,
    [switch]$VerifyRedisRestart,
    [switch]$VerifyDuplicateDelivery,
    [switch]$VerifyRabbitRecovery,
    [switch]$VerifyCompensation
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    Write-Host "PASS $Message"
}

$suffix = [guid]::NewGuid().ToString("N")
$password = "ci-voucher-$suffix"
$registrations = @()
foreach ($index in 1..2) {
    $registration = Invoke-RestMethod -Method Post -Uri "$Api/auth/register" -ContentType "application/json" `
        -Body (@{ email = "ci-voucher-$index-$suffix@example.test"; password = $password; displayName = "Voucher test $index" } | ConvertTo-Json)
    $registrations += $registration
}
$adminId = $registrations[0].user.id
if ($adminId -notmatch '^[0-9a-f-]{36}$') { throw "Unexpected test user ID" }
$dbPassword = if ($env:MYSQL_PASSWORD) { $env:MYSQL_PASSWORD } else { "gameweare" }
docker compose exec -T -e "MYSQL_PWD=$dbPassword" mysql mysql -ugameweare -N -B gameweare -e `
    "UPDATE users SET role='admin' WHERE id='$adminId'" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to prepare test admin" }
$adminLogin = Invoke-RestMethod -Method Post -Uri "$Api/auth/login" -ContentType "application/json" `
    -Body (@{ email = "ci-voucher-1-$suffix@example.test"; password = $password } | ConvertTo-Json)
$adminHeaders = @{ Authorization = "Bearer $($adminLogin.accessToken)" }

$starts = (Get-Date).ToUniversalTime().AddSeconds(33)
$campaign = Invoke-RestMethod -Method Post -Uri "$Api/maintenance/voucher-campaigns" -Headers $adminHeaders `
    -ContentType "application/json" -Body (@{
        title = "CI stock-one $suffix"; startsAt = $starts.ToString("o")
        endsAt = $starts.AddMinutes(5).ToString("o"); stock = 1
    } | ConvertTo-Json)
Start-Sleep -Seconds 35

$targetA = "$Api/voucher-campaigns/$($campaign.id)/claim"
$targetB = "$ApiReplica/voucher-campaigns/$($campaign.id)/claim"
$tokens = @($adminLogin.accessToken, $registrations[1].accessToken)
$samples = 1..$Requests | ForEach-Object -ThrottleLimit 20 -Parallel {
    $number = $_
    $allTokens = $using:tokens
    $firstUrl = $using:targetA
    $secondUrl = $using:targetB
    $token = $allTokens[$number % 2]
    $url = if ($number % 2 -eq 0) { $firstUrl } else { $secondUrl }
    $timer = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $response = Invoke-RestMethod -Method Post -Uri $url -Headers @{ Authorization = "Bearer $token" }
        $status = $response.status
    } catch {
        $status = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { "network-error" }
    }
    $timer.Stop()
    [pscustomobject]@{ status = $status; milliseconds = $timer.Elapsed.TotalMilliseconds }
}
Start-Sleep -Seconds 5
$report = Invoke-RestMethod -Uri "$Api/maintenance/voucher-campaigns/$($campaign.id)/reconcile" -Headers $adminHeaders
if (-not ($report.totalStock -eq 1 -and $report.issuedCount -eq 1 -and $report.remainingStock -eq 0 -and $report.mysqlBalanced)) {
    $statuses = @($samples | Group-Object status | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ", "
    Write-Host "DIAGNOSTIC campaign=$($campaign.id) statuses=[$statuses] report=$($report | ConvertTo-Json -Compress)"
}
Assert ($report.totalStock -eq 1 -and $report.issuedCount -eq 1 -and $report.remainingStock -eq 0 -and $report.mysqlBalanced) `
    "Stock one never oversells and MySQL reconciles"

$states = @()
for ($index = 0; $index -lt 2; $index++) {
    $states += (Invoke-RestMethod -Uri "$Api/voucher-campaigns/$($campaign.id)/claims/me" `
        -Headers @{ Authorization = "Bearer $($tokens[$index])" }).status
}
Assert (@($states | Where-Object { $_ -eq "issued" }).Count -eq 1) "Exactly one user receives a voucher"
$winner = if ($states[0] -eq "issued") { 0 } else { 1 }
$ordered = @($samples | Sort-Object milliseconds)
$p95 = $ordered[[math]::Ceiling($ordered.Count * 0.95) - 1].milliseconds
Write-Host "RESULT requests=$Requests p95_ms=$([math]::Round($p95, 1)) issued=$($report.issuedCount) remaining=$($report.remainingStock) redis_stock=$($report.redisStock)"
Write-Host "NOTE P95 covers concurrent claim responses only; use a load generator for sustained throughput."

if ($VerifyRedemption) {
    $winnerHeaders = @{ Authorization = "Bearer $($tokens[$winner])" }
    $wallet = Invoke-RestMethod -Uri "$Api/vouchers/me" -Headers $winnerHeaders
    $voucher = @($wallet | Where-Object { $_.sourceId -eq $campaign.id -and $_.status -eq "available" })[0]
    Assert ($null -ne $voucher) "Winner receives an available generation voucher"
    $jobBody = @{ prompt = "Build a keyboard-controlled canvas game with scoring"; agentMode = "chat"
        createType = "init"; fundingMode = "voucher"; voucherId = $voucher.id } | ConvertTo-Json
    $job = Invoke-RestMethod -Method Post -Uri "$Api/create/jobs" -Headers $winnerHeaders `
        -ContentType "application/json" -Body $jobBody
    try {
        Invoke-RestMethod -Method Post -Uri "$ApiReplica/create/jobs" -Headers $winnerHeaders `
            -ContentType "application/json" -Body $jobBody | Out-Null
        throw "The same voucher started a second job"
    } catch {
        $responseProperty = $_.Exception.PSObject.Properties['Response']
        $httpStatus = if ($responseProperty -and $responseProperty.Value) {
            [int]$responseProperty.Value.StatusCode
        } else { $null }
        if ($httpStatus -ne 409) { throw }
    }
    Write-Host "PASS The same voucher cannot fund concurrent jobs"
    $deadline = (Get-Date).AddMinutes(5)
    do {
        Start-Sleep -Seconds 3
        $state = Invoke-RestMethod -Uri "$Api/create/jobs/$($job.id)" -Headers $winnerHeaders
    } while ($state.status -notin @("completed", "failed", "canceled") -and (Get-Date) -lt $deadline)
    Assert ($state.status -eq "completed") "Voucher-funded job produces a playable version"
    $wallet = Invoke-RestMethod -Uri "$Api/vouchers/me" -Headers $winnerHeaders
    Assert (@($wallet | Where-Object { $_.id -eq $voucher.id })[0].status -eq "used") "Completed job consumes its voucher"
    $published = Invoke-RestMethod -Method Post -Uri "$Api/create/jobs/$($job.id)/publish" -Headers $winnerHeaders
    $document = Invoke-WebRequest -Uri "$Api/play/$($published.gameSlug)/document" -Headers $winnerHeaders
    Assert ($document.StatusCode -eq 200 -and $document.Content.Contains("<canvas")) "Published voucher game can be played"
}

if ($VerifyDuplicateDelivery) {
    $winnerHeaders = @{ Authorization = "Bearer $($tokens[$winner])" }
    $claim = Invoke-RestMethod -Uri "$Api/voucher-campaigns/$($campaign.id)/claims/me" -Headers $winnerHeaders
    $rabbitPassword = if ($env:RABBITMQ_PASSWORD) { $env:RABBITMQ_PASSWORD } else { "gameweare" }
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("gameweare:$rabbitPassword"))
    $message = @{ properties = @{}; routing_key = "claim"; payload = "$($campaign.id)|$($registrations[$winner].user.id)|$($claim.reservationId)|0|0"; payload_encoding = "string" } | ConvertTo-Json -Compress
    $published = Invoke-RestMethod -Method Post -Uri "http://localhost:15673/api/exchanges/%2F/gameweare.voucher/publish" `
        -Headers @{ Authorization = "Basic $basic" } -ContentType "application/json" -Body $message
    Assert ($published.routed) "Duplicate RabbitMQ delivery is routed"
    Start-Sleep -Seconds 3
    $again = Invoke-RestMethod -Uri "$Api/maintenance/voucher-campaigns/$($campaign.id)/reconcile" -Headers $adminHeaders
    Assert ($again.issuedCount -eq 1 -and $again.remainingStock -eq 0) "Duplicate RabbitMQ delivery does not decrement MySQL stock"
}

if ($VerifyRabbitRecovery) {
    $startsAgain = (Get-Date).ToUniversalTime().AddSeconds(33)
    $recoveryCampaign = Invoke-RestMethod -Method Post -Uri "$Api/maintenance/voucher-campaigns" -Headers $adminHeaders `
        -ContentType "application/json" -Body (@{
            title = "CI Rabbit recovery $suffix"; startsAt = $startsAgain.ToString("o")
            endsAt = $startsAgain.AddMinutes(5).ToString("o"); stock = 1
        } | ConvertTo-Json)
    Start-Sleep -Seconds 35
    docker compose stop rabbitmq | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "RabbitMQ stop failed" }
    try {
        $reserved = Invoke-RestMethod -Method Post -Uri "$Api/voucher-campaigns/$($recoveryCampaign.id)/claim" -Headers $adminHeaders
        Assert ($reserved.status -eq "pending") "Redis accepts provisional reservation during RabbitMQ outage"
    } finally {
        docker compose start rabbitmq | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "RabbitMQ restart failed" }
    }
    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 2
        $claimState = Invoke-RestMethod -Uri "$Api/voucher-campaigns/$($recoveryCampaign.id)/claims/$($reserved.reservationId)" -Headers $adminHeaders
    } while ($claimState.status -ne "issued" -and (Get-Date) -lt $deadline)
    Assert ($claimState.status -eq "issued") "Stream relay delivers reservation after RabbitMQ recovery"
    $recovered = Invoke-RestMethod -Uri "$Api/maintenance/voucher-campaigns/$($recoveryCampaign.id)/reconcile" -Headers $adminHeaders
    Assert ($recovered.mysqlBalanced -and $recovered.issuedCount -eq 1 -and $recovered.remainingStock -eq 0) `
        "Recovered RabbitMQ campaign reconciles"
}

if ($VerifyCompensation) {
    $startsAgain = (Get-Date).ToUniversalTime().AddSeconds(33)
    $failureCampaign = Invoke-RestMethod -Method Post -Uri "$Api/maintenance/voucher-campaigns" -Headers $adminHeaders `
        -ContentType "application/json" -Body (@{
            title = "CI compensation $suffix"; startsAt = $startsAgain.ToString("o")
            endsAt = $startsAgain.AddMinutes(5).ToString("o"); stock = 1
        } | ConvertTo-Json)
    Start-Sleep -Seconds 35
    docker compose stop rabbitmq | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "RabbitMQ stop failed" }
    try {
        $reserved = Invoke-RestMethod -Method Post -Uri "$Api/voucher-campaigns/$($failureCampaign.id)/claim" -Headers $adminHeaders
        Assert ($reserved.status -eq "pending") "Failure test reserves one provisional voucher"
        # Fault injection: make the MySQL stock update reject this test activity before delivery resumes.
        docker compose exec -T -e "MYSQL_PWD=$dbPassword" mysql mysql -ugameweare -N -B gameweare -e `
            "UPDATE voucher_campaigns SET status='canceled' WHERE id='$($failureCampaign.id)'" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Campaign fault injection failed" }
    } finally {
        docker compose start rabbitmq | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "RabbitMQ restart failed" }
    }
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        $claimState = Invoke-RestMethod -Uri "$Api/voucher-campaigns/$($failureCampaign.id)/claims/$($reserved.reservationId)" -Headers $adminHeaders
    } while ($claimState.status -ne "failed" -and (Get-Date) -lt $deadline)
    Assert ($claimState.status -eq "failed") "Failed MySQL issuance eventually releases the provisional reservation"
    $reconciled = Invoke-RestMethod -Uri "$Api/maintenance/voucher-campaigns/$($failureCampaign.id)/reconcile" -Headers $adminHeaders
    Assert ($reconciled.mysqlBalanced -and $reconciled.issuedCount -eq 0 -and $reconciled.remainingStock -eq 1 `
            -and $reconciled.redisStock -eq "1" -and $reconciled.provisionalReservations -eq 0) `
        "Compensated campaign has no voucher, no oversell, and restored Redis stock"
}

if ($VerifyRedisRestart) {
    docker compose restart redis | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Redis restart failed" }
    $deadline = (Get-Date).AddSeconds(60)
    $after = $null
    do {
        try {
            $after = Invoke-RestMethod -Uri "$Api/maintenance/voucher-campaigns/$($campaign.id)/reconcile" -Headers $adminHeaders
            if ($after.redisStock -eq "0") { break }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    Assert ($null -ne $after -and $after.redisStock -eq "0" -and $after.issuedCount -eq 1 -and $after.mysqlBalanced) `
        "Redis restart preserves issued campaign stock and MySQL balance"
}
