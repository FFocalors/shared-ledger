<#
.SYNOPSIS
    Runs a two-account Activity/RLS smoke against the local Supabase API.

.DESCRIPTION
    This is a local API/RLS prerequisite for P6. It creates two ephemeral
    authenticated users through the public signup endpoint, exercises only
    the frozen Activity/Participant RPCs, and leaves the resulting local
    records for inspection. A local Supabase reset removes them.

    The script deliberately does not use service-role credentials, direct
    database connections, admin Auth APIs, hosted projects, or business
    expense/financial/storage/realtime operations.
#>

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$localPropertiesPath = Join-Path $repoRoot "local.properties"

$script:passCount = 0
$script:failCount = 0
$script:stepCount = 0
$script:failureReported = $false
$script:currentStep = "startup"
$script:currentStatus = 0
$script:client = $null

function Get-LocalProperty {
    param([Parameter(Mandatory)][string]$Name)

    $line = Get-Content -LiteralPath $localPropertiesPath |
        Where-Object { $_ -match ("^" + [regex]::Escape($Name) + "=") } |
        Select-Object -First 1
    if ($null -eq $line) {
        return $null
    }
    return (($line -split "=", 2)[1].Trim() -replace "\\:", ":" -replace "\\/", "/" -replace "\\\\", "\")
}

function Get-StatusClass {
    param([int]$StatusCode)
    if ($StatusCode -ge 200 -and $StatusCode -lt 300) { return "2xx" }
    if ($StatusCode -ge 400 -and $StatusCode -lt 500) { return "4xx" }
    if ($StatusCode -ge 500 -and $StatusCode -lt 600) { return "5xx" }
    return "HTTP-$StatusCode"
}

function Add-Pass {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$StatusCode,
        [string]$Uuid
    )
    $script:stepCount++
    $script:passCount++
    $suffix = if ($Uuid) { " UUID=$Uuid" } else { "" }
    Write-Output ("PASS {0} HTTP={1}{2}" -f $Name, (Get-StatusClass $StatusCode), $suffix)
}

function Add-Fail {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][int]$StatusCode,
        [Parameter(Mandatory)][string]$Class
    )
    $script:stepCount++
    $script:failCount++
    $script:failureReported = $true
    Write-Output ("FAIL {0} HTTP={1} CLASS={2}" -f $Name, (Get-StatusClass $StatusCode), $Class)
    throw [System.InvalidOperationException]::new("local API smoke failed")
}

function Get-ErrorClass {
    param([int]$StatusCode, [string]$Body, [switch]$Signup)

    $safeBody = if ($Body) { $Body } else { "" }
    if ($Signup -and $safeBody -match "(?i)confirm|confirmation|email") {
        return "AUTH_CONFIRMATION_REQUIRED"
    }
    if ($safeBody -match "42501|permission|creator|not an activity member") {
        return "PERMISSION_DENIED"
    }
    if ($safeBody -match "P0002|not found") {
        return "NOT_FOUND"
    }
    return ("HTTP_{0}" -f $StatusCode)
}

function Invoke-LocalApi {
    param(
        [Parameter(Mandatory)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [string]$AccessToken,
        [object]$Body
    )

    $request = [System.Net.Http.HttpRequestMessage]::new(
        [System.Net.Http.HttpMethod]::$Method,
        ($script:baseUrl + $Path))
    [void]$request.Headers.TryAddWithoutValidation("apikey", $script:publishableKey)
    if ($AccessToken) {
        $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $AccessToken)
    }
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 20 -Compress
        $request.Content = [System.Net.Http.StringContent]::new(
            $json,
            [System.Text.Encoding]::UTF8,
            "application/json")
    }

    try {
        $response = $script:client.SendAsync($request).GetAwaiter().GetResult()
        $responseBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        return [pscustomobject]@{
            StatusCode = [int]$response.StatusCode
            Body = $responseBody
        }
    } finally {
        $request.Dispose()
    }
}

function Convert-JsonBody {
    param([Parameter(Mandatory)]$Response, [Parameter(Mandatory)][string]$Name)
    try {
        return ($Response.Body | ConvertFrom-Json)
    } catch {
        Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class "INVALID_JSON"
    }
}

function Get-FirstRow {
    param([Parameter(Mandatory)]$Response, [Parameter(Mandatory)][string]$Name)
    $parsed = Convert-JsonBody -Response $Response -Name $Name
    if ($parsed -is [array]) {
        if ($parsed.Count -lt 1) {
            Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class "EMPTY_RESULT"
        }
        return $parsed[0]
    }
    return $parsed
}

function Require-Success {
    param(
        [Parameter(Mandatory)]$Response,
        [Parameter(Mandatory)][string]$Name,
        [switch]$Signup
    )
    if ($Response.StatusCode -lt 200 -or $Response.StatusCode -ge 300) {
        Add-Fail -Name $Name -StatusCode $Response.StatusCode -Class (Get-ErrorClass -StatusCode $Response.StatusCode -Body $Response.Body -Signup:$Signup)
    }
}

function Read-Session {
    param([Parameter(Mandatory)][string]$Role, [Parameter(Mandatory)][string]$Email, [Parameter(Mandatory)][string]$Password)

    $response = Invoke-LocalApi -Method POST -Path "/auth/v1/signup" -Body @{
        email = $Email
        password = $Password
    }
    Require-Success -Response $response -Name ("{0} signup" -f $Role) -Signup
    $parsed = Convert-JsonBody -Response $response -Name ("{0} signup" -f $Role)
    $token = [string]$parsed.access_token
    $userId = [string]$parsed.user.id
    if ([string]::IsNullOrWhiteSpace($token) -or [string]::IsNullOrWhiteSpace($userId)) {
        Add-Fail -Name ("{0} signup" -f $Role) -StatusCode $response.StatusCode -Class "AUTH_CONFIRMATION_REQUIRED"
    }
    Add-Pass -Name ("{0} signup" -f $Role) -StatusCode $response.StatusCode | Out-Host
    return [pscustomobject]@{ AccessToken = $token; UserId = $userId }
}

function Invoke-Rpc {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][hashtable]$Body
    )
    $response = Invoke-LocalApi -Method POST -Path ("/rest/v1/rpc/{0}" -f $Name) -AccessToken $Token -Body $Body
    Require-Success -Response $response -Name $Name
    return $response
}

function Invoke-Read {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][string]$Path
    )
    $response = Invoke-LocalApi -Method GET -Path $Path -AccessToken $Token
    Require-Success -Response $response -Name $Name
    return $response
}

try {
    if (-not (Test-Path -LiteralPath $localPropertiesPath -PathType Leaf)) {
        Add-Fail -Name "local configuration" -StatusCode 0 -Class "LOCAL_PROPERTIES_MISSING"
    }

    $configuredUrl = Get-LocalProperty -Name "SUPABASE_URL"
    $script:publishableKey = Get-LocalProperty -Name "SUPABASE_PUBLISHABLE_KEY"
    $normalizedUrl = if ($configuredUrl) { $configuredUrl.TrimEnd("/") } else { "" }
    if ($normalizedUrl -notmatch "^http://(127\.0\.0\.1|localhost):54321$") {
        Add-Fail -Name "local URL configuration" -StatusCode 0 -Class "LOOPBACK_54321_REQUIRED"
    }
    if ([string]::IsNullOrWhiteSpace($script:publishableKey)) {
        Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "PUBLISHABLE_KEY_MISSING"
    }
    if ($script:publishableKey -match "(?i)service[_-]?role|sb_secret|secret") {
        Add-Fail -Name "publishable key configuration" -StatusCode 0 -Class "SECRET_KEY_REJECTED"
    }
    $script:baseUrl = $normalizedUrl

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.UseProxy = $false
    $script:client = [System.Net.Http.HttpClient]::new($handler)

    $runId = [guid]::NewGuid().ToString("N")
    $creatorPassword = ([guid]::NewGuid().ToString("N") + "A9!z" + [guid]::NewGuid().ToString("N"))
    $memberPassword = ([guid]::NewGuid().ToString("N") + "B8!y" + [guid]::NewGuid().ToString("N"))
    $creatorEmail = "p6-creator-$runId@example.invalid"
    $memberEmail = "p6-member-$runId@example.invalid"

    $creator = Read-Session -Role "A" -Email $creatorEmail -Password $creatorPassword
    $member = Read-Session -Role "B" -Email $memberEmail -Password $memberPassword

    $createResponse = Invoke-Rpc -Name "create_activity" -Token $creator.AccessToken -Body @{
        name = "P6 API smoke $runId"
        type = "normal"
        base_currency = "CNY"
        multi_currency_enabled = $false
    }
    $createRow = Get-FirstRow -Response $createResponse -Name "A create activity"
    $activityId = [string]$createRow.activity_id
    $joinCode = [string]$createRow.join_code
    if ($activityId -notmatch "^[0-9a-fA-F-]{36}$" -or [string]::IsNullOrWhiteSpace($joinCode)) {
        Add-Fail -Name "A create activity" -StatusCode $createResponse.StatusCode -Class "INVALID_ACTIVITY_RESULT"
    }
    Add-Pass -Name "A create activity" -StatusCode $createResponse.StatusCode -Uuid $activityId

    $creatorParticipantResponse = Invoke-Rpc -Name "create_participant" -Token $creator.AccessToken -Body @{
        activity_id = $activityId
        name = "P6 creator participant $runId"
        participant_order = 0
    }
    $creatorParticipantRow = Get-FirstRow -Response $creatorParticipantResponse -Name "A create participant"
    $creatorParticipantId = [string]$creatorParticipantRow.participant_id
    if ($creatorParticipantId -notmatch "^[0-9a-fA-F-]{36}$") {
        Add-Fail -Name "A create participant" -StatusCode $creatorParticipantResponse.StatusCode -Class "INVALID_PARTICIPANT_RESULT"
    }
    Add-Pass -Name "A create participant" -StatusCode $creatorParticipantResponse.StatusCode -Uuid $creatorParticipantId

    $memberParticipantResponse = Invoke-Rpc -Name "create_participant" -Token $creator.AccessToken -Body @{
        activity_id = $activityId
        name = "P6 member participant $runId"
        participant_order = 1
    }
    $memberParticipantRow = Get-FirstRow -Response $memberParticipantResponse -Name "A create second participant"
    $memberParticipantId = [string]$memberParticipantRow.participant_id
    if ($memberParticipantId -notmatch "^[0-9a-fA-F-]{36}$") {
        Add-Fail -Name "A create second participant" -StatusCode $memberParticipantResponse.StatusCode -Class "INVALID_PARTICIPANT_RESULT"
    }
    Add-Pass -Name "A create second participant" -StatusCode $memberParticipantResponse.StatusCode -Uuid $memberParticipantId

    $joinResponse = Invoke-Rpc -Name "join_activity_by_code" -Token $member.AccessToken -Body @{ join_code = $joinCode }
    $joinRow = Get-FirstRow -Response $joinResponse -Name "B join activity"
    if ([string]$joinRow.activity_id -ne $activityId) {
        Add-Fail -Name "B join activity" -StatusCode $joinResponse.StatusCode -Class "JOIN_ACTIVITY_MISMATCH"
    }
    Add-Pass -Name "B join activity" -StatusCode $joinResponse.StatusCode

    $claimResponse = Invoke-Rpc -Name "claim_participant" -Token $member.AccessToken -Body @{
        activity_id = $activityId
        participant_id = $memberParticipantId
    }
    $claimRow = Get-FirstRow -Response $claimResponse -Name "B claim participant"
    if ([string]$claimRow.claimed_participant_id -ne $memberParticipantId) {
        Add-Fail -Name "B claim participant" -StatusCode $claimResponse.StatusCode -Class "CLAIM_PARTICIPANT_MISMATCH"
    }
    Add-Pass -Name "B claim participant" -StatusCode $claimResponse.StatusCode

    foreach ($account in @($creator, $member)) {
        $label = if ($account.UserId -eq $creator.UserId) { "A" } else { "B" }
        $activityRead = Invoke-Read -Name ("{0} read activity" -f $label) -Token $account.AccessToken -Path ("/rest/v1/activities?id=eq.{0}&select=id,created_by" -f $activityId)
        $activityRows = @(Convert-JsonBody -Response $activityRead -Name ("{0} read activity" -f $label))
        if ($activityRows.Count -ne 1 -or [string]$activityRows[0].id -ne $activityId) {
            Add-Fail -Name ("{0} read activity" -f $label) -StatusCode $activityRead.StatusCode -Class "ACTIVITY_FACT_MISSING"
        }
        Add-Pass -Name ("{0} read activity" -f $label) -StatusCode $activityRead.StatusCode

        $membersRead = Invoke-Read -Name ("{0} read members" -f $label) -Token $account.AccessToken -Path ("/rest/v1/activity_members?activity_id=eq.{0}&select=id,user_id" -f $activityId)
        $memberRows = @(Convert-JsonBody -Response $membersRead -Name ("{0} read members" -f $label))
        if ($memberRows.Count -ne 2) {
            Add-Fail -Name ("{0} read members" -f $label) -StatusCode $membersRead.StatusCode -Class "MEMBER_FACT_MISSING"
        }
        Add-Pass -Name ("{0} read members" -f $label) -StatusCode $membersRead.StatusCode

        $participantsRead = Invoke-Read -Name ("{0} read participants" -f $label) -Token $account.AccessToken -Path ("/rest/v1/participants?activity_id=eq.{0}&select=id,activity_id" -f $activityId)
        $participantRows = @(Convert-JsonBody -Response $participantsRead -Name ("{0} read participants" -f $label))
        $participantIds = @($participantRows | ForEach-Object { [string]$_.id })
        if ($participantIds.Count -ne 2 -or $participantIds -notcontains $creatorParticipantId -or $participantIds -notcontains $memberParticipantId) {
            Add-Fail -Name ("{0} read participants" -f $label) -StatusCode $participantsRead.StatusCode -Class "PARTICIPANT_FACT_MISSING"
        }
        Add-Pass -Name ("{0} read participants" -f $label) -StatusCode $participantsRead.StatusCode

        $claimsRead = Invoke-Read -Name ("{0} read claims" -f $label) -Token $account.AccessToken -Path ("/rest/v1/participant_claims?activity_id=eq.{0}&select=id,participant_id,user_id" -f $activityId)
        $claimRows = @(Convert-JsonBody -Response $claimsRead -Name ("{0} read claims" -f $label))
        if ($claimRows.Count -ne 1 -or [string]$claimRows[0].participant_id -ne $memberParticipantId -or [string]$claimRows[0].user_id -ne $member.UserId) {
            Add-Fail -Name ("{0} read claims" -f $label) -StatusCode $claimsRead.StatusCode -Class "CLAIM_FACT_MISSING"
        }
        Add-Pass -Name ("{0} read claims" -f $label) -StatusCode $claimsRead.StatusCode
    }

    $privateCreateResponse = Invoke-Rpc -Name "create_activity" -Token $creator.AccessToken -Body @{
        name = "P6 private API smoke $runId"
        type = "normal"
        base_currency = "CNY"
        multi_currency_enabled = $false
    }
    $privateCreateRow = Get-FirstRow -Response $privateCreateResponse -Name "A create private activity"
    $privateActivityId = [string]$privateCreateRow.activity_id
    if ($privateActivityId -notmatch "^[0-9a-fA-F-]{36}") {
        Add-Fail -Name "A create private activity" -StatusCode $privateCreateResponse.StatusCode -Class "INVALID_ACTIVITY_RESULT"
    }
    Add-Pass -Name "A create private activity" -StatusCode $privateCreateResponse.StatusCode -Uuid $privateActivityId

    $privateRead = Invoke-LocalApi -Method GET -Path ("/rest/v1/activities?id=eq.{0}&select=id" -f $privateActivityId) -AccessToken $member.AccessToken
    if ($privateRead.StatusCode -ge 200 -and $privateRead.StatusCode -lt 300) {
        $privateRows = @(Convert-JsonBody -Response $privateRead -Name "B private activity read")
        if ($privateRows.Count -ne 0) {
            Add-Fail -Name "B private activity read" -StatusCode $privateRead.StatusCode -Class "RLS_VISIBILITY_LEAK"
        }
    } elseif ($privateRead.StatusCode -lt 400 -or $privateRead.StatusCode -ge 500) {
        Add-Fail -Name "B private activity read" -StatusCode $privateRead.StatusCode -Class "RLS_NEGATIVE_UNCONFIRMED"
    }
    Add-Pass -Name "B private activity read denied" -StatusCode $privateRead.StatusCode

    $creatorOnlyResponse = Invoke-LocalApi -Method POST -Path "/rest/v1/rpc/update_activity_settings" -AccessToken $member.AccessToken -Body @{
        activity_id = $activityId
        name = "P6 denied settings attempt $runId"
        base_currency = "CNY"
        multi_currency_enabled = $false
    }
    if ($creatorOnlyResponse.StatusCode -lt 400 -or $creatorOnlyResponse.StatusCode -ge 500) {
        Add-Fail -Name "B creator-only settings denied" -StatusCode $creatorOnlyResponse.StatusCode -Class "CREATOR_GUARD_FAILED"
    }
    if ($creatorOnlyResponse.Body -notmatch "42501|permission|creator|activity member") {
        Add-Fail -Name "B creator-only settings denied" -StatusCode $creatorOnlyResponse.StatusCode -Class "PERMISSION_ERROR_UNCONFIRMED"
    }
    Add-Pass -Name "B creator-only settings denied" -StatusCode $creatorOnlyResponse.StatusCode

    Write-Output ("SUMMARY PASS={0} FAIL={1} TOTAL={2}" -f $script:passCount, $script:failCount, $script:stepCount)
} catch {
    if (-not $script:failureReported) {
        $script:stepCount++
        $script:failCount++
        Write-Output ("FAIL {0} HTTP={1} CLASS=SCRIPT_ERROR" -f $script:currentStep, (Get-StatusClass $script:currentStatus))
    }
    Write-Output ("SUMMARY PASS={0} FAIL={1} TOTAL={2}" -f $script:passCount, $script:failCount, $script:stepCount)
    exit 1
} finally {
    if ($null -ne $script:client) {
        $script:client.Dispose()
    }
}
