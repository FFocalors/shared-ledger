<#
.SYNOPSIS
    Companion for one Android device running account A and desktop account B.

.DESCRIPTION
    Creates a temporary ordinary account B, joins the Activity using an
    operator-supplied join code, claims one unclaimed Participant, and listens
    for the Activity UPDATE produced by account A on the device. It uses only
    the local loopback Supabase API and never prints credentials, raw response
    bodies, join codes, or WebSocket frames.
#>

[CmdletBinding()]
param(
    [string]$ParticipantName,
    [int]$TimeoutSeconds = 30,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"
$script:baseUrl = $null; $script:publishableKey = $null; $script:httpClient = $null; $script:socket = $null
$script:topic = $null; $script:passCount = 0; $script:failCount = 0; $script:stepCount = 0; $script:failureReported = $false; $script:stage = "startup"

function Show-Usage {
    Write-Output "Usage: .\scripts\run-local-device-realtime-companion.ps1 [-ParticipantName <name>] [-TimeoutSeconds <seconds>]"
    Write-Output "The script reads the join code through hidden SecureString input, creates desktop account B, claims one available Participant, and waits for A's Activity name update."
}

function Read-JoinCodeSecurely {
    $secureValue = Read-Host -AsSecureString "请输入真机 A 当前 Activity 的加入码（输入隐藏且不记录）"
    if ($null -eq $secureValue) { return $null }
    $bstr = [System.IntPtr]::Zero
    try {
        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        if ($bstr -ne [System.IntPtr]::Zero) {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
        $secureValue.Dispose()
    }
}

function Get-LocalProperty {
    param([Parameter(Mandatory)][string]$Name)
    $line = Get-Content -LiteralPath $localPropertiesPath | Where-Object { $_ -match ("^" + [regex]::Escape($Name) + "=") } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return (($line -split "=", 2)[1].Trim() -replace "\\:", ":" -replace "\\/", "/" -replace "\\\\", "\")
}

function Get-StatusClass {
    param([int]$StatusCode)
    if ($StatusCode -ge 200 -and $StatusCode -lt 300) { return "2xx" }
    if ($StatusCode -ge 400 -and $StatusCode -lt 500) { return "4xx" }
    if ($StatusCode -ge 500 -and $StatusCode -lt 600) { return "5xx" }
    if ($StatusCode -eq 101) { return "101" }
    return "HTTP-$StatusCode"
}

function Add-Pass {
    param([string]$Name, [int]$StatusCode, [string]$Uuid, [string]$NameHash, [int]$NameLength)
    $script:stepCount++; $script:passCount++
    $parts = @("PASS $Name HTTP=$(Get-StatusClass $StatusCode)")
    if ($Uuid) { $parts += "UUID=$Uuid" }
    if ($NameHash) { $parts += "NAME_SHA256=$NameHash NAME_LENGTH=$NameLength" }
    Write-Output ($parts -join " ")
}

function Add-Fail {
    param([string]$Name, [int]$StatusCode, [string]$Class)
    $script:stepCount++; $script:failCount++; $script:failureReported = $true
    Write-Output "FAIL $Name HTTP=$(Get-StatusClass $StatusCode) CLASS=$Class"
    throw [System.InvalidOperationException]::new("local companion failed")
}

function Invoke-LocalApi {
    param([ValidateSet("GET", "POST")][string]$Method, [string]$Path, [string]$AccessToken, [object]$Body)
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::$Method, ($script:baseUrl + $Path))
    [void]$request.Headers.TryAddWithoutValidation("apikey", $script:publishableKey)
    if ($AccessToken) { $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $AccessToken) }
    if ($null -ne $Body) { $request.Content = [System.Net.Http.StringContent]::new(($Body | ConvertTo-Json -Depth 20 -Compress), [System.Text.Encoding]::UTF8, "application/json") }
    try {
        $response = $script:httpClient.SendAsync($request).GetAwaiter().GetResult()
        return [pscustomobject]@{ StatusCode = [int]$response.StatusCode; Body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() }
    } finally { $request.Dispose() }
}

function Convert-JsonBody {
    param($Response, [string]$Name)
    try { return ($Response.Body | ConvertFrom-Json) } catch { Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class "INVALID_JSON" }
}

function Invoke-Rpc {
    param([string]$Name, [string]$Token, [hashtable]$Body)
    $response = Invoke-LocalApi -Method POST -Path "/rest/v1/rpc/$Name" -AccessToken $Token -Body $Body
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) { Add-Fail -Name $Name -StatusCode $response.StatusCode -Class "HTTP_$($response.StatusCode)" }
    return $response
}

function New-Session {
    param([string]$Role, [string]$Email, [string]$Password)
    $response = Invoke-LocalApi -Method POST -Path "/auth/v1/signup" -Body @{ email = $Email; password = $Password }
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        $class = if ($response.Body -match "(?i)confirm|confirmation|email") { "AUTH_CONFIRMATION_REQUIRED" } else { "AUTH_SIGNUP_HTTP_$($response.StatusCode)" }
        Add-Fail -Name "$Role signup" -StatusCode $response.StatusCode -Class $class
    }
    $parsed = Convert-JsonBody -Response $response -Name "$Role signup"
    $token = [string]$parsed.access_token; $userId = [string]$parsed.user.id
    if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($userId)) { Add-Fail -Name "$Role signup" -StatusCode $response.StatusCode -Class "AUTH_CONFIRMATION_REQUIRED" }
    Add-Pass -Name "$Role signup" -StatusCode $response.StatusCode | Out-Host
    return [pscustomobject]@{ AccessToken = $token; UserId = $userId }
}

function Send-RealtimeMessage {
    param([System.Net.WebSockets.ClientWebSocket]$Socket, [hashtable]$Message)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($Message | ConvertTo-Json -Depth 20 -Compress))
    [void]$Socket.SendAsync([System.ArraySegment[byte]]::new($bytes), [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
}

function Receive-RealtimeMessage {
    param([System.Net.WebSockets.ClientWebSocket]$Socket, [int]$TimeoutSeconds)
    $buffer = [byte[]]::new(65536); $builder = [System.Text.StringBuilder]::new(); $cancel = [System.Threading.CancellationTokenSource]::new(); $cancel.CancelAfter($TimeoutSeconds * 1000)
    try {
        do {
            $result = $Socket.ReceiveAsync([System.ArraySegment[byte]]::new($buffer), $cancel.Token).GetAwaiter().GetResult()
            if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) { return $null }
            if ($result.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text) { return [pscustomobject]@{ InvalidFrame = $true } }
            [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
        } while (-not $result.EndOfMessage)
        try { return ($builder.ToString() | ConvertFrom-Json) } catch { return [pscustomobject]@{ InvalidJson = $true } }
    } catch [System.OperationCanceledException] { return $null
    } catch {
        if ($cancel.IsCancellationRequested) { return $null }
        throw
    } finally { $cancel.Dispose() }
}

function Join-Realtime {
    param([string]$Token, [string]$Topic, [string]$ActivityId)
    $uri = [System.Uri]::new(("ws://{0}/realtime/v1/websocket?apikey={1}&vsn=1.0.0" -f $script:baseUrl.Substring(7), [System.Uri]::EscapeDataString($script:publishableKey)))
    $script:socket = [System.Net.WebSockets.ClientWebSocket]::new(); $script:socket.Options.Proxy = $null
    [void]$script:socket.ConnectAsync($uri, [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
    $joinRef = "1"
    Send-RealtimeMessage -Socket $script:socket -Message @{
        topic = $Topic; event = "phx_join"; ref = $joinRef; join_ref = $joinRef
        payload = @{
            config = @{ broadcast = @{ ack = $false; self = $false }; presence = @{ enabled = $false }; postgres_changes = @(@{ event = "UPDATE"; schema = "public"; table = "activities"; filter = "id=eq.$ActivityId" }); private = $false }
            access_token = $Token
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(15); $reply = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = [math]::Max(1, [int][math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))
        $message = Receive-RealtimeMessage -Socket $script:socket -TimeoutSeconds ([math]::Min(5, $remaining))
        if ($null -eq $message) { Send-RealtimeMessage -Socket $script:socket -Message @{ topic = "phoenix"; event = "heartbeat"; ref = ([guid]::NewGuid().ToString("N")); payload = @{} }; continue }
        if ($message.InvalidFrame -or $message.InvalidJson) { Add-Fail -Name "B Realtime join" -StatusCode 101 -Class "INVALID_FRAME" }
        if ([string]$message.event -eq "phx_reply" -and [string]$message.ref -eq $joinRef) { $reply = $message; break }
    }
    if ($null -eq $reply) { Add-Fail -Name "B Realtime join" -StatusCode 101 -Class "JOIN_TIMEOUT" }
    if ([string]$reply.payload.status -ne "ok") { Add-Fail -Name "B Realtime join" -StatusCode 101 -Class "JOIN_REJECTED" }
    $subscriptions = @($reply.payload.response.postgres_changes)
    if ($subscriptions.Count -ne 1 -or [string]$subscriptions[0].event -ne "UPDATE" -or [string]$subscriptions[0].schema -ne "public" -or [string]$subscriptions[0].table -ne "activities") { Add-Fail -Name "B Realtime join" -StatusCode 101 -Class "SUBSCRIPTION_MISMATCH" }
    $script:topic = $Topic
    Add-Pass -Name "B subscribe activities" -StatusCode 101 | Out-Host
    return [pscustomobject]@{ SubscriptionId = [string]$subscriptions[0].id; Topic = $Topic }
}

function Get-NameHash {
    param([string]$Name)
    return ([Convert]::ToHexString([System.Security.Cryptography.SHA256]::HashData([System.Text.Encoding]::UTF8.GetBytes($Name)))).ToLowerInvariant()
}

function Wait-ActivityUpdate {
    param($Subscription, [string]$ActivityId, [string]$OldName, [int]$Timeout)
    $deadline = [DateTime]::UtcNow.AddSeconds($Timeout)
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = [math]::Max(1, [int][math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))
        $message = Receive-RealtimeMessage -Socket $script:socket -TimeoutSeconds ([math]::Min(5, $remaining))
        if ($null -eq $message) { Send-RealtimeMessage -Socket $script:socket -Message @{ topic = "phoenix"; event = "heartbeat"; ref = ([guid]::NewGuid().ToString("N")); payload = @{} }; continue }
        if ($message.InvalidFrame -or $message.InvalidJson) { Add-Fail -Name "B receive activities UPDATE" -StatusCode 101 -Class "INVALID_FRAME" }
        if ([string]$message.topic -ne $Subscription.Topic -or [string]$message.event -ne "postgres_changes") { continue }
        $payload = $message.payload; $data = $payload.data; $ids = @($payload.ids | ForEach-Object { [string]$_ })
        if ($ids -notcontains $Subscription.SubscriptionId -or [string]$data.schema -ne "public" -or [string]$data.table -ne "activities" -or [string]$data.type -ne "UPDATE") { continue }
        $record = $data.record
        if ([string]$record.id -eq $ActivityId -and -not [string]::IsNullOrWhiteSpace([string]$record.name) -and [string]$record.name -ne $OldName) {
            return [string]$record.name
        }
    }
    Add-Fail -Name "B receive activities UPDATE" -StatusCode 101 -Class "EVENT_TIMEOUT_OR_MISMATCH"
}

function Close-Realtime {
    if ($null -eq $script:socket) { return }
    try {
        if ($script:socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            if ($script:topic) { Send-RealtimeMessage -Socket $script:socket -Message @{ topic = $script:topic; event = "phx_leave"; ref = "leave"; join_ref = "1"; payload = @{} } }
            [void]$script:socket.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "done", [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
        }
    } catch { }
    $script:socket.Dispose()
}

try {
    if ($Help) { Show-Usage; exit 0 }
    if ($TimeoutSeconds -lt 10 -or $TimeoutSeconds -gt 300) { Add-Fail -Name "arguments" -StatusCode 0 -Class "TIMEOUT_OUT_OF_RANGE" }
    if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) { Add-Fail -Name "local configuration" -StatusCode 0 -Class "LOCAL_PROPERTIES_MISSING" }
    $configuredUrl = Get-LocalProperty -Name "SUPABASE_URL"; $script:publishableKey = Get-LocalProperty -Name "SUPABASE_PUBLISHABLE_KEY"; $normalizedUrl = if ($configuredUrl) { $configuredUrl.TrimEnd("/") } else { "" }
    if ($normalizedUrl -notmatch "^http://(127\.0\.0\.1|localhost):54321$") { Add-Fail -Name "local URL configuration" -StatusCode 0 -Class "LOOPBACK_54321_REQUIRED" }
    if ([string]::IsNullOrWhiteSpace($script:publishableKey)) { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "PUBLISHABLE_KEY_MISSING" }
    if ($script:publishableKey -match "(?i)service[_-]?role|sb_secret|secret") { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "SECRET_KEY_REJECTED" }
    $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.UseProxy = $false; $script:httpClient = [System.Net.Http.HttpClient]::new($handler); $script:baseUrl = $normalizedUrl
    $runId = [guid]::NewGuid().ToString("N")
    $script:stage = "signup"; $b = New-Session -Role "B" -Email "p6-device-b-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "B8!y" + [guid]::NewGuid().ToString("N")))
    $joinCode = Read-JoinCodeSecurely
    try {
        if ([string]::IsNullOrWhiteSpace($joinCode)) { Add-Fail -Name "join code input" -StatusCode 0 -Class "JOIN_CODE_MISSING" }
        $script:stage = "join"; $joined = Invoke-Rpc -Name "join_activity_by_code" -Token $b.AccessToken -Body @{ join_code = $joinCode }
    } finally {
        $joinCode = $null
    }
    $joinedRow = @(Convert-JsonBody -Response $joined -Name "B join activity")[0]; $activityId = [string]$joinedRow.activity_id
    if ($activityId -notmatch "^[0-9a-fA-F-]{36}$") { Add-Fail -Name "B join activity" -StatusCode $joined.StatusCode -Class "INVALID_ACTIVITY_RESULT" }
    Add-Pass -Name "B join activity" -StatusCode $joined.StatusCode -Uuid $activityId
    $script:stage = "claim-selection"; $participantsResponse = Invoke-LocalApi -Method GET -Path "/rest/v1/participants?activity_id=eq.$activityId&select=id,name" -AccessToken $b.AccessToken
    if ($participantsResponse.StatusCode -lt 200 -or $participantsResponse.StatusCode -ge 300) { Add-Fail -Name "B read participants" -StatusCode $participantsResponse.StatusCode -Class "HTTP_$($participantsResponse.StatusCode)" }
    $participants = @(Convert-JsonBody -Response $participantsResponse -Name "B read participants")
    $claimsResponse = Invoke-LocalApi -Method GET -Path "/rest/v1/participant_claims?activity_id=eq.$activityId&select=participant_id" -AccessToken $b.AccessToken
    if ($claimsResponse.StatusCode -lt 200 -or $claimsResponse.StatusCode -ge 300) { Add-Fail -Name "B read participant claims" -StatusCode $claimsResponse.StatusCode -Class "HTTP_$($claimsResponse.StatusCode)" }
    $claimedIds = @((Convert-JsonBody -Response $claimsResponse -Name "B read participant claims") | ForEach-Object { [string]$_.participant_id })
    $available = @($participants | Where-Object { $claimedIds -notcontains [string]$_.id })
    if ($ParticipantName) { $available = @($available | Where-Object { [string]$_.name -ceq $ParticipantName }) }
    if ($available.Count -ne 1) { Add-Fail -Name "B select claimable participant" -StatusCode $participantsResponse.StatusCode -Class "CLAIM_TARGET_AMBIGUOUS_OR_MISSING" }
    $participantId = [string]$available[0].id
    $claim = Invoke-Rpc -Name "claim_participant" -Token $b.AccessToken -Body @{ activity_id = $activityId; participant_id = $participantId }
    Add-Pass -Name "B claim participant" -StatusCode $claim.StatusCode -Uuid $participantId
    $script:stage = "subscribe"; $activityRead = Invoke-LocalApi -Method GET -Path "/rest/v1/activities?id=eq.$activityId&select=id,name" -AccessToken $b.AccessToken
    if ($activityRead.StatusCode -lt 200 -or $activityRead.StatusCode -ge 300) { Add-Fail -Name "B read activity" -StatusCode $activityRead.StatusCode -Class "HTTP_$($activityRead.StatusCode)" }
    $activityRows = @(Convert-JsonBody -Response $activityRead -Name "B read activity")
    if ($activityRows.Count -ne 1 -or [string]$activityRows[0].id -ne $activityId) { Add-Fail -Name "B read activity" -StatusCode $activityRead.StatusCode -Class "ACTIVITY_FACT_MISSING" }
    $oldName = [string]$activityRows[0].name
    $subscription = Join-Realtime -Token $b.AccessToken -Topic "realtime:p6-device-companion-$runId" -ActivityId $activityId
    Write-Output "ACTION 在真机 A 修改该 Activity 名称；脚本将在 $TimeoutSeconds 秒内等待 B 收到精确 activities UPDATE 事件。"
    $script:stage = "wait-event"; $eventName = Wait-ActivityUpdate -Subscription $subscription -ActivityId $activityId -OldName $oldName -Timeout $TimeoutSeconds
    Add-Pass -Name "B receive activities UPDATE" -StatusCode 101 -Uuid $activityId -NameHash (Get-NameHash $eventName) -NameLength $eventName.Length
    $finalRead = Invoke-LocalApi -Method GET -Path "/rest/v1/activities?id=eq.$activityId&select=id,name" -AccessToken $b.AccessToken
    if ($finalRead.StatusCode -lt 200 -or $finalRead.StatusCode -ge 300) { Add-Fail -Name "B reread activity" -StatusCode $finalRead.StatusCode -Class "HTTP_$($finalRead.StatusCode)" }
    $finalRows = @(Convert-JsonBody -Response $finalRead -Name "B reread activity")
    if ($finalRows.Count -ne 1 -or [string]$finalRows[0].id -ne $activityId -or [string]$finalRows[0].name -ne $eventName) { Add-Fail -Name "B reread activity" -StatusCode $finalRead.StatusCode -Class "FINAL_ACTIVITY_MISMATCH" }
    Add-Pass -Name "B reread final activity" -StatusCode $finalRead.StatusCode -Uuid $activityId -NameHash (Get-NameHash ([string]$finalRows[0].name)) -NameLength ([string]$finalRows[0].name).Length
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"
} catch {
    if (-not $script:failureReported) { $script:stepCount++; $script:failCount++; Write-Output "FAIL $script:stage HTTP=HTTP-0 CLASS=SCRIPT_ERROR" }
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"; exit 1
} finally { Close-Realtime; if ($null -ne $script:httpClient) { $script:httpClient.Dispose() } }
