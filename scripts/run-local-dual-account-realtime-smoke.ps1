<#
.SYNOPSIS
    Runs a local two-account Supabase Realtime Postgres Changes smoke.

.DESCRIPTION
    Uses only ordinary authenticated users and the local loopback API. The
    script verifies subscription acknowledgements and the exact Postgres
    Changes payload for a participant_claims INSERT and an activities UPDATE.
    It never prints credentials or raw WebSocket frames. Local test records
    remain until the local Supabase project is reset.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"
$script:baseUrl = $null
$script:publishableKey = $null
$script:httpClient = $null
$script:sockets = [System.Collections.Generic.List[System.Net.WebSockets.ClientWebSocket]]::new()
$script:passCount = 0
$script:failCount = 0
$script:stepCount = 0
$script:failureReported = $false
$script:stage = "startup"

function Get-LocalProperty {
    param([Parameter(Mandatory)][string]$Name)
    $line = Get-Content -LiteralPath $localPropertiesPath |
        Where-Object { $_ -match ("^" + [regex]::Escape($Name) + "=") } |
        Select-Object -First 1
    if ($null -eq $line) { return $null }
    return (($line -split "=", 2)[1].Trim() -replace "\\:", ":" -replace "\\/", "/" -replace "\\\\", "\")
}

function Get-StatusClass {
    param([int]$StatusCode)
    if ($StatusCode -ge 200 -and $StatusCode -lt 300) { return "2xx" }
    if ($StatusCode -ge 400 -and $StatusCode -lt 500) { return "4xx" }
    if ($StatusCode -ge 500 -and $StatusCode -lt 600) { return "5xx" }
    if ($StatusCode -eq 101) { return "101" }
    return ("HTTP-{0}" -f $StatusCode)
}

function Add-Pass {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][int]$StatusCode, [string]$Event, [string]$Table, [string]$Uuid)
    $script:stepCount++; $script:passCount++
    $parts = @("PASS $Name HTTP=$(Get-StatusClass $StatusCode)")
    if ($Event) { $parts += "EVENT=$Event" }
    if ($Table) { $parts += "TABLE=$Table" }
    if ($Uuid) { $parts += "UUID=$Uuid" }
    Write-Output ($parts -join " ")
}

function Add-Fail {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][int]$StatusCode, [Parameter(Mandatory)][string]$Class)
    $script:stepCount++; $script:failCount++; $script:failureReported = $true
    Write-Output "FAIL $Name HTTP=$(Get-StatusClass $StatusCode) CLASS=$Class"
    throw [System.InvalidOperationException]::new("local realtime smoke failed")
}

function Invoke-LocalApi {
    param([ValidateSet("GET", "POST")][string]$Method, [string]$Path, [string]$AccessToken, [object]$Body)
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::$Method, ($script:baseUrl + $Path))
    [void]$request.Headers.TryAddWithoutValidation("apikey", $script:publishableKey)
    if ($AccessToken) { $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $AccessToken) }
    if ($null -ne $Body) {
        $request.Content = [System.Net.Http.StringContent]::new(($Body | ConvertTo-Json -Depth 20 -Compress), [System.Text.Encoding]::UTF8, "application/json")
    }
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
    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        Add-Fail -Name $Name -StatusCode $response.StatusCode -Class "HTTP_$($response.StatusCode)"
    }
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
    if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($userId)) {
        Add-Fail -Name "$Role signup" -StatusCode $response.StatusCode -Class "AUTH_CONFIRMATION_REQUIRED"
    }
    Add-Pass -Name "$Role signup" -StatusCode $response.StatusCode | Out-Host
    return [pscustomobject]@{ AccessToken = $token; UserId = $userId }
}

function Send-RealtimeMessage {
    param([System.Net.WebSockets.ClientWebSocket]$Socket, [hashtable]$Message)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes(($Message | ConvertTo-Json -Depth 20 -Compress))
    $segment = [System.ArraySegment[byte]]::new($bytes)
    [void]$Socket.SendAsync($segment, [System.Net.WebSockets.WebSocketMessageType]::Text, $true, [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
}

function Receive-RealtimeMessage {
    param([System.Net.WebSockets.ClientWebSocket]$Socket, [int]$TimeoutSeconds)
    $buffer = [byte[]]::new(65536); $builder = [System.Text.StringBuilder]::new()
    $cancel = [System.Threading.CancellationTokenSource]::new()
    $cancel.CancelAfter($TimeoutSeconds * 1000)
    try {
        do {
            $result = $Socket.ReceiveAsync([System.ArraySegment[byte]]::new($buffer), $cancel.Token).GetAwaiter().GetResult()
            if ($result.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) { return $null }
            if ($result.MessageType -ne [System.Net.WebSockets.WebSocketMessageType]::Text) { return [pscustomobject]@{ InvalidFrame = $true } }
            [void]$builder.Append([System.Text.Encoding]::UTF8.GetString($buffer, 0, $result.Count))
        } while (-not $result.EndOfMessage)
        try { return ($builder.ToString() | ConvertFrom-Json) } catch { return [pscustomobject]@{ InvalidJson = $true } }
    } catch [System.OperationCanceledException] {
        return $null
    } catch {
        # PowerShell may wrap task cancellation in MethodInvocationException.
        # Only convert it to a timeout when our own cancellation token fired;
        # all genuine WebSocket failures remain visible to the outer handler.
        if ($cancel.IsCancellationRequested) { return $null }
        throw
    } finally { $cancel.Dispose() }
}

function Join-Realtime {
    param([string]$Role, [string]$Token, [string]$Topic, [string]$Table, [string]$Event, [string]$Filter, [string]$ActivityId)
    $uri = [System.Uri]::new(("ws://{0}/realtime/v1/websocket?apikey={1}&vsn=1.0.0" -f $script:baseUrl.Substring(7), [System.Uri]::EscapeDataString($script:publishableKey)))
    $socket = [System.Net.WebSockets.ClientWebSocket]::new()
    # Keep loopback traffic off any inherited corporate/HTTP proxy.
    $socket.Options.Proxy = $null
    [void]$socket.ConnectAsync($uri, [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
    [void]$script:sockets.Add($socket)
    $joinRef = "1"; $joinMessage = @{
        topic = $Topic; event = "phx_join"; ref = $joinRef; join_ref = $joinRef
        payload = @{
            config = @{ broadcast = @{ ack = $false; self = $false }; presence = @{ enabled = $false }; postgres_changes = @(@{ event = $Event; schema = "public"; table = $Table; filter = $Filter }); private = $false }
            access_token = $Token
        }
    }
    Send-RealtimeMessage -Socket $socket -Message $joinMessage
    $deadline = [DateTime]::UtcNow.AddSeconds(15); $reply = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = [math]::Max(1, [int][math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))
        $message = Receive-RealtimeMessage -Socket $socket -TimeoutSeconds ([math]::Min(5, $remaining))
        if ($null -eq $message) {
            Send-RealtimeMessage -Socket $socket -Message @{ topic = "phoenix"; event = "heartbeat"; ref = ([guid]::NewGuid().ToString("N")); payload = @{} }
            continue
        }
        if ($message.InvalidFrame -or $message.InvalidJson) { Add-Fail -Name "$Role Realtime join" -StatusCode 101 -Class "INVALID_FRAME" }
        if ([string]$message.event -eq "phx_reply" -and [string]$message.ref -eq $joinRef) { $reply = $message; break }
    }
    if ($null -eq $reply) { Add-Fail -Name "$Role Realtime join" -StatusCode 101 -Class "JOIN_TIMEOUT" }
    if ([string]$reply.payload.status -ne "ok") { Add-Fail -Name "$Role Realtime join" -StatusCode 101 -Class "JOIN_REJECTED" }
    $subscriptions = @($reply.payload.response.postgres_changes)
    if ($subscriptions.Count -ne 1 -or [string]$subscriptions[0].event -ne $Event -or [string]$subscriptions[0].schema -ne "public" -or [string]$subscriptions[0].table -ne $Table) {
        Add-Fail -Name "$Role Realtime join" -StatusCode 101 -Class "SUBSCRIPTION_MISMATCH"
    }
    Add-Pass -Name "$Role subscribe $Table" -StatusCode 101 -Event $Event -Table $Table | Out-Host
    return [pscustomobject]@{ Socket = $socket; Topic = $Topic; JoinRef = $joinRef; SubscriptionId = [string]$subscriptions[0].id; ActivityId = $ActivityId; Table = $Table; Event = $Event }
}

function Wait-ExpectedChange {
    param($Subscription, [hashtable]$ExpectedRecord, [string]$Role)
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline) {
        $remaining = [math]::Max(1, [int][math]::Ceiling(($deadline - [DateTime]::UtcNow).TotalSeconds))
        $message = Receive-RealtimeMessage -Socket $Subscription.Socket -TimeoutSeconds ([math]::Min(5, $remaining))
        if ($null -eq $message) {
            Send-RealtimeMessage -Socket $Subscription.Socket -Message @{ topic = "phoenix"; event = "heartbeat"; ref = ([guid]::NewGuid().ToString("N")); payload = @{} }
            continue
        }
        if ($message.InvalidFrame -or $message.InvalidJson) { Add-Fail -Name "$Role Realtime event" -StatusCode 101 -Class "INVALID_FRAME" }
        if ([string]$message.topic -ne $Subscription.Topic -or [string]$message.event -ne "postgres_changes") { continue }
        $payload = $message.payload; $data = $payload.data
        $ids = @($payload.ids | ForEach-Object { [string]$_ })
        if ($ids -notcontains $Subscription.SubscriptionId -or [string]$data.schema -ne "public" -or [string]$data.table -ne $Subscription.Table -or [string]$data.type -ne $Subscription.Event) { continue }
        $record = $data.record; $matches = $true
        foreach ($key in $ExpectedRecord.Keys) { if ([string]$record.$key -ne [string]$ExpectedRecord[$key]) { $matches = $false; break } }
        if ($matches) {
            Add-Pass -Name "$Role receives $($Subscription.Table) $($Subscription.Event)" -StatusCode 101 -Event $Subscription.Event -Table $Subscription.Table -Uuid $Subscription.ActivityId
            return
        }
    }
    Add-Fail -Name "$Role receives $($Subscription.Table) $($Subscription.Event)" -StatusCode 101 -Class "EVENT_TIMEOUT_OR_MISMATCH"
}

function Close-RealtimeSocket {
    param([System.Net.WebSockets.ClientWebSocket]$Socket, [string]$Topic, [string]$JoinRef)
    if ($null -eq $Socket) { return }
    try {
        if ($Socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            if ($Topic) {
                Send-RealtimeMessage -Socket $Socket -Message @{ topic = $Topic; event = "phx_leave"; ref = "leave"; join_ref = $JoinRef; payload = @{} }
            }
            [void]$Socket.CloseAsync([System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure, "done", [System.Threading.CancellationToken]::None).GetAwaiter().GetResult()
        }
    } catch { }
    $Socket.Dispose()
}

try {
    if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) { Add-Fail -Name "local configuration" -StatusCode 0 -Class "LOCAL_PROPERTIES_MISSING" }
    $configuredUrl = Get-LocalProperty -Name "SUPABASE_URL"; $script:publishableKey = Get-LocalProperty -Name "SUPABASE_PUBLISHABLE_KEY"
    $normalizedUrl = if ($configuredUrl) { $configuredUrl.TrimEnd("/") } else { "" }
    if ($normalizedUrl -notmatch "^http://(127\.0\.0\.1|localhost):54321$") { Add-Fail -Name "local URL configuration" -StatusCode 0 -Class "LOOPBACK_54321_REQUIRED" }
    if ([string]::IsNullOrWhiteSpace($script:publishableKey)) { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "PUBLISHABLE_KEY_MISSING" }
    if ($script:publishableKey -match "(?i)service[_-]?role|sb_secret|secret") { Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "SECRET_KEY_REJECTED" }
    $script:baseUrl = $normalizedUrl
    $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.UseProxy = $false
    $script:httpClient = [System.Net.Http.HttpClient]::new($handler)
    $runId = [guid]::NewGuid().ToString("N")
    $script:stage = "signup"
    $a = New-Session -Role "A" -Email "p6-rt-a-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "A9!z" + [guid]::NewGuid().ToString("N")))
    $b = New-Session -Role "B" -Email "p6-rt-b-$runId@example.invalid" -Password (([guid]::NewGuid().ToString("N") + "B8!y" + [guid]::NewGuid().ToString("N")))
    $script:stage = "setup"
    $created = Invoke-Rpc -Name "create_activity" -Token $a.AccessToken -Body @{ name = "P6 Realtime smoke $runId"; type = "normal"; base_currency = "CNY"; multi_currency_enabled = $false }
    $activityRows = @(Convert-JsonBody -Response $created -Name "A create activity")
    $activity = $activityRows[0]
    $activityId = [string]$activity.activity_id; $joinCode = [string]$activity.join_code
    if ($activityId -notmatch "^[0-9a-fA-F-]{36}$" -or [string]::IsNullOrWhiteSpace($joinCode)) { Add-Fail -Name "A create activity" -StatusCode $created.StatusCode -Class "INVALID_ACTIVITY_RESULT" }
    Add-Pass -Name "A create activity" -StatusCode $created.StatusCode -Uuid $activityId
    $p1Rows = @(Convert-JsonBody -Response (Invoke-Rpc -Name "create_participant" -Token $a.AccessToken -Body @{ activity_id = $activityId; name = "P6 RT A $runId"; participant_order = 0 }) -Name "A create participant")
    $p1 = $p1Rows[0]
    $p2Rows = @(Convert-JsonBody -Response (Invoke-Rpc -Name "create_participant" -Token $a.AccessToken -Body @{ activity_id = $activityId; name = "P6 RT B $runId"; participant_order = 1 }) -Name "A create second participant")
    $p2 = $p2Rows[0]
    $participantId = [string]$p2.participant_id
    if ($participantId -notmatch "^[0-9a-fA-F-]{36}$") { Add-Fail -Name "A create participants" -StatusCode 200 -Class "INVALID_PARTICIPANT_RESULT" }
    Add-Pass -Name "A create participants" -StatusCode 200
    $script:stage = "join-claim"
    $claimSubscription = Join-Realtime -Role "A" -Token $a.AccessToken -Topic "realtime:p6-rt-claim-$runId" -Table "participant_claims" -Event "INSERT" -Filter "activity_id=eq.$activityId" -ActivityId $activityId
    $joined = Invoke-Rpc -Name "join_activity_by_code" -Token $b.AccessToken -Body @{ join_code = $joinCode }
    Add-Pass -Name "B join activity" -StatusCode $joined.StatusCode
    $claim = Invoke-Rpc -Name "claim_participant" -Token $b.AccessToken -Body @{ activity_id = $activityId; participant_id = $participantId }
    Add-Pass -Name "B claim participant" -StatusCode $claim.StatusCode
    $script:stage = "wait-claim"
    Wait-ExpectedChange -Subscription $claimSubscription -ExpectedRecord @{ activity_id = $activityId; participant_id = $participantId; user_id = $b.UserId } -Role "A"
    $script:stage = "join-activity"
    $activitySubscription = Join-Realtime -Role "B" -Token $b.AccessToken -Topic "realtime:p6-rt-activity-$runId" -Table "activities" -Event "UPDATE" -Filter "id=eq.$activityId" -ActivityId $activityId
    $script:stage = "wait-activity"
    $newName = "P6 Realtime updated $runId"
    $updated = Invoke-Rpc -Name "update_activity_settings" -Token $a.AccessToken -Body @{ activity_id = $activityId; name = $newName; base_currency = "CNY"; multi_currency_enabled = $false }
    Add-Pass -Name "A update activity settings" -StatusCode $updated.StatusCode
    Wait-ExpectedChange -Subscription $activitySubscription -ExpectedRecord @{ id = $activityId; name = $newName } -Role "B"
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"
} catch {
    if (-not $script:failureReported) { $script:stepCount++; $script:failCount++; Write-Output "FAIL $script:stage HTTP=HTTP-0 CLASS=SCRIPT_ERROR" }
    Write-Output "SUMMARY PASS=$script:passCount FAIL=$script:failCount TOTAL=$script:stepCount"
    exit 1
} finally {
    foreach ($socket in @($script:sockets)) { Close-RealtimeSocket -Socket $socket -Topic "" -JoinRef "1" }
    if ($null -ne $script:httpClient) { $script:httpClient.Dispose() }
}
