# Run against an isolated API configured for scripts/mock_llm.py. Creates synthetic test accounts only.
param([string]$Api='http://localhost:18080', [string]$ReplicaApi='', [string]$MockBaseUrl='http://mock-llm:8080')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
function Assert($condition,[string]$message) { if (-not $condition) { throw $message }; Write-Host "PASS $message" }
function Call([string]$path,$body=$null,$headers=$script:headers) {
    $args=@{Uri="$Api$path";Headers=$headers;TimeoutSec=240}
    if ($null -ne $body) { $args.Method='Post';$args.ContentType='application/json';$args.Body=($body | ConvertTo-Json -Depth 20 -Compress) }
    Invoke-RestMethod @args
}
function ExpectStatus([int]$code,[scriptblock]$action) {
    try { & $action | Out-Null; throw "Expected HTTP $code" }
    catch { if ($null -eq $_.Exception.Response -or [int]$_.Exception.Response.StatusCode -ne $code) { throw }; Write-Host "PASS HTTP $code" }
}
$deadline=(Get-Date).AddSeconds(120)
do {
    try { $health=Invoke-RestMethod -Uri "$Api/health" -TimeoutSec 3; if ($health.status -eq 'ok') { break } }
    catch { Start-Sleep -Seconds 2 }
    if ((Get-Date) -ge $deadline) { throw 'Chat test API did not become healthy' }
} while ($true)
$headers=@{}
$user=Call '/auth/register' @{email="chat-$([guid]::NewGuid().ToString('N'))@example.test";password='chat-test-password';displayName='Chat integration test'}
$headers=@{Authorization="Bearer $($user.accessToken)"}
Invoke-RestMethod -Method Put -Uri "$Api/create/ai-config" -Headers $headers -ContentType 'application/json' `
    -Body (@{baseUrl=$MockBaseUrl;model='mock';apiKey='mock-chat-test-key'} | ConvertTo-Json) | Out-Null
$skills=Call '/create/chat/skills'
Assert (@($skills).Count -ge 5) 'Reviewed skill catalog available'
$id=[guid]::NewGuid().ToString()
$session=Call '/create/chat/sessions' @{id=$id;createType='init';fundingMode='byok'}
Assert ($session.revision -eq 0 -and $session.status -eq 'draft') 'Chat starts without a generation task'
$first=@{message='我想做一个星空跑酷';requestId=[guid]::NewGuid().ToString();revision=0}
$session=Call "/create/chat/sessions/$id/messages" $first
Assert ($session.revision -eq 1 -and @($session.messages).Count -eq 2 -and -not $session.ready) 'First turn persists messages and partial brief'
Assert ('game-interview' -in $session.messages[1].skillIds) 'Model autonomously reads skill through tool'
$repeat=Call "/create/chat/sessions/$id/messages" $first
Assert ($repeat.revision -eq 1 -and @($repeat.messages).Count -eq 2) 'Retried turn does not duplicate messages'
if ($ReplicaApi) { $Api=$ReplicaApi; Write-Host 'Continuing the same conversation on another API instance' }
ExpectStatus 409 { Call "/create/chat/sessions/$id/messages" @{message='更换内容';requestId=$first.requestId;revision=0} }
ExpectStatus 409 { Call "/create/chat/sessions/$id/confirm" @{revision=1} }
$other=Call '/auth/register' @{email="chat-other-$([guid]::NewGuid().ToString('N'))@example.test";password='chat-test-password';displayName='Other chat user'} @{}
$otherHeaders=@{Authorization="Bearer $($other.accessToken)"}
ExpectStatus 404 { Call "/create/chat/sessions/$id" $null $otherHeaders }
ExpectStatus 404 { Call "/create/chat/sessions/$id/confirm" @{revision=1} $otherHeaders }
$session=Call "/create/chat/sessions/$id/messages" @{message='使用方向键移动，撞到陨石结束，100分获胜，可以重试';requestId=[guid]::NewGuid().ToString();revision=1}
Assert ($session.revision -eq 2 -and $session.ready -and @($session.messages).Count -eq 4) 'Second turn refines complete brief'
$reloaded=Call "/create/chat/sessions/$id"
Assert ($reloaded.brief.controls -eq '方向键移动' -and @($reloaded.messages).Count -eq 4) 'History and brief survive page reload'
$jobs=Call '/create/jobs'
Assert ($null -eq $jobs -or $jobs.Count -eq 0) 'No generation job before explicit confirmation'
ExpectStatus 409 { Call '/create/jobs' @{prompt='必须先访谈';agentMode='chat';createType='init';fundingMode='byok'} }
ExpectStatus 409 { Call "/create/chat/sessions/$id/confirm" @{revision=1} }
$job=Call "/create/chat/sessions/$id/confirm" @{revision=2}
$same=Call "/create/chat/sessions/$id/confirm" @{revision=2}
Assert ($job.id -eq $same.id -and $job.agentMode -eq 'react') 'Confirm hands off to one ReAct job idempotently'
Assert ($job.displayTitle -eq '星空跑酷') 'Task title comes from the reviewed game brief'
$deadline=(Get-Date).AddMinutes(3)
do {
    $job=Call "/create/jobs/$($job.id)"
    if ($job.status -in @('completed','failed','canceled')) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
Assert ($job.status -eq 'completed') "ReAct generates a validated game (status=$($job.status))"
$published=Call "/create/jobs/$($job.id)/publish" @{}
Assert ($published.publishStatus -eq 'published') 'Generated draft publishes through existing flow'
Write-Host 'Guided Chat -> confirmed brief -> Outbox -> ReAct -> validation -> publish: PASS'
