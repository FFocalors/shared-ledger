[CmdletBinding()]
param(
    [string[]] $Tests,
    [switch] $KeepStack,
    [string] $ExistingProjectRoot
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$runId = [Guid]::NewGuid().ToString('N').Substring(0, 10)
$isExistingProject = -not [string]::IsNullOrWhiteSpace($ExistingProjectRoot)
$projectId = "sl-dbtest-$runId"
$isolatedRoot = Join-Path $tempBase "shared-ledger-dbtests-$runId"
if ($isExistingProject) {
    $isolatedRoot = (Resolve-Path -LiteralPath $ExistingProjectRoot).Path
    $resolvedTemp = $tempBase.TrimEnd('\') + '\'
    if (-not $isolatedRoot.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($isolatedRoot) -notlike 'shared-ledger-dbtests-*') {
        throw "Existing project must be a shared-ledger-dbtests-* directory under the system temp directory: $isolatedRoot"
    }
}
$isolatedSupabase = Join-Path $isolatedRoot 'supabase'
$stackPrepared = $false

function Get-FreePortBlock([int] $count) {
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        $candidate = Get-Random -Minimum 55000 -Maximum 62000
        $listeners = @()
        try {
            for ($offset = 0; $offset -lt $count; $offset++) {
                $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, ($candidate + $offset))
                $listener.Start()
                $listeners += $listener
            }
            return $candidate
        }
        catch {
            continue
        }
        finally {
            foreach ($listener in $listeners) { $listener.Stop() }
        }
    }
    throw 'Could not reserve a free port block for the isolated database project.'
}

function Set-TomlSectionPort([string] $Text, [string] $Section, [string] $Key, [int] $Port) {
    $pattern = "(?ms)(^\[$([regex]::Escape($Section))\]\s*\r?\n(?:(?!^\[).)*?^$([regex]::Escape($Key))\s*=\s*)\d+"
    $updated = [regex]::Replace($Text, $pattern, ('$1' + $Port), 1)
    if ($updated -ceq $Text) {
        $sectionHeader = "(?m)(^\[$([regex]::Escape($Section))\]\s*\r?\n)"
        $updated = [regex]::Replace($Text, $sectionHeader, ('$1' + $Key + ' = ' + $Port + "`r`n"), 1)
    }
    if ($updated -ceq $Text) { throw "Could not set [$Section].$Key in isolated config.toml." }
    return $updated
}

if ($isExistingProject) {
    $configPath = Join-Path $isolatedSupabase 'config.toml'
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Existing isolated Supabase project has no config.toml: $configPath"
    }
    $existingConfig = Get-Content -LiteralPath $configPath -Raw
    $projectIdMatch = [regex]::Match($existingConfig, '(?m)^project_id\s*=\s*"([a-z0-9-]+)"')
    if (-not $projectIdMatch.Success -or $projectIdMatch.Groups[1].Value -eq 'shared-ledger') {
        throw 'Refusing to attach to a project without a unique isolated project_id.'
    }
    $projectId = $projectIdMatch.Groups[1].Value
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'supabase\tests') -Destination $isolatedSupabase -Recurse -Force
}
else {
    if (Test-Path -LiteralPath $isolatedRoot) { throw "Refusing to overwrite existing temp path: $isolatedRoot" }
    New-Item -ItemType Directory -Path $isolatedSupabase -Force | Out-Null
    $stackPrepared = $true
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'supabase\config.toml') -Destination $isolatedSupabase
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'supabase\seed.sql') -Destination $isolatedSupabase
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'supabase\migrations') -Destination $isolatedSupabase -Recurse
    Copy-Item -LiteralPath (Join-Path $sourceRoot 'supabase\tests') -Destination $isolatedSupabase -Recurse
}

$configPath = Join-Path $isolatedSupabase 'config.toml'
if (-not $isExistingProject) {
    $config = Get-Content -LiteralPath $configPath -Raw
    $config = [regex]::Replace($config, '(?m)^project_id\s*=\s*"[^"]+"', "project_id = `"$projectId`"", 1)
    $portBase = Get-FreePortBlock 7
    $config = Set-TomlSectionPort $config 'api' 'port' ($portBase + 1)
    $config = Set-TomlSectionPort $config 'db' 'port' ($portBase + 2)
    $config = Set-TomlSectionPort $config 'db' 'shadow_port' ($portBase + 3)
    $config = Set-TomlSectionPort $config 'studio' 'port' ($portBase + 4)
    $config = Set-TomlSectionPort $config 'local_smtp' 'port' ($portBase + 5)
    $config = Set-TomlSectionPort $config 'storage' 'port' ($portBase + 6)
    Set-Content -LiteralPath $configPath -Value $config -NoNewline
}

$testDir = Join-Path $isolatedSupabase 'tests\database'
$selectedTests = if ($Tests -and $Tests.Count -gt 0) {
    $Tests | ForEach-Object {
        $name = [IO.Path]::GetFileName($_)
        if ($name -eq 'phase8_transfer_restore.sql') { throw 'phase8_transfer_restore.sql is RETIRED and intentionally excluded from execution.' }
        $candidate = Join-Path $testDir $name
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { throw "Unknown database test: $_" }
        $candidate
    }
} else {
    Get-ChildItem -LiteralPath $testDir -Filter '*.sql' -File |
        Where-Object { $_.Name -notin @('legacy_rpc_fixture_adapters.sql', 'phase8_transfer_restore.sql') } |
        Sort-Object Name |
        ForEach-Object FullName
}
if ($selectedTests.Count -eq 0) { throw 'No database tests were selected.' }

try {
    if (-not $isExistingProject) {
        $excluded = 'gotrue,realtime,imgproxy,kong,mailpit,postgrest,postgres-meta,studio,edge-runtime,logflare,vector,supavisor'
        & supabase start --exclude $excluded --workdir $isolatedRoot
        if ($LASTEXITCODE -ne 0) { throw "supabase start failed with exit code $LASTEXITCODE." }
        & supabase db reset --local --yes --workdir $isolatedRoot
        if ($LASTEXITCODE -ne 0) { throw "supabase db reset failed with exit code $LASTEXITCODE." }
    }

    $containerName = "supabase_db_$projectId"
    $container = & docker ps --filter "name=^/$containerName$" --format '{{.Names}}'
    if ($LASTEXITCODE -ne 0 -or $container -notcontains $containerName) {
        throw "Could not locate isolated database container $containerName."
    }
    $containerSettings = & docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' $containerName
    if ($LASTEXITCODE -ne 0) { throw 'Could not read connection settings from the isolated database container.' }
    $dbName = ($containerSettings | Where-Object { $_ -like 'POSTGRES_DB=*' } | Select-Object -First 1) -replace '^POSTGRES_DB=', ''
    $dbUser = ($containerSettings | Where-Object { $_ -like 'POSTGRES_USER=*' } | Select-Object -First 1) -replace '^POSTGRES_USER=', ''
    $dbPassword = ($containerSettings | Where-Object { $_ -like 'POSTGRES_PASSWORD=*' } | Select-Object -First 1) -replace '^POSTGRES_PASSWORD=', ''
    if ([string]::IsNullOrWhiteSpace($dbName) -or [string]::IsNullOrWhiteSpace($dbUser) -or [string]::IsNullOrWhiteSpace($dbPassword)) {
        throw 'The isolated database container did not provide a complete test connection.'
    }
    $userUri = [Uri]::EscapeDataString($dbUser)
    $passwordUri = [Uri]::EscapeDataString($dbPassword)
    $databaseUri = [Uri]::EscapeDataString($dbName)
    $connUri = "postgresql://$userUri`:$passwordUri@$containerName`:5432/$databaseUri"
    $dbtestEnvPath = Join-Path $testDir '.dbtest_env.sql'
    [IO.File]::WriteAllText(
        $dbtestEnvPath,
        "\set db_conninfo $connUri`r`n",
        [Text.UTF8Encoding]::new($false)
    )

    $relativeTests = $selectedTests | ForEach-Object {
        'database/' + [IO.Path]::GetFileName($_)
    }
    Push-Location -LiteralPath $isolatedRoot
    try {
        $cliOutput = @(& supabase test db --local @relativeTests 2>&1)
        $cliExitCode = $LASTEXITCODE
        $cliOutput | ForEach-Object { Write-Host $_ }
        if ($cliExitCode -eq 0) { return }

        $cliText = $cliOutput -join [Environment]::NewLine
        $containerTempBase = $tempBase.Replace('\', '/').TrimEnd('/')
        $containerTempBase = [regex]::Replace($containerTempBase, '^[A-Za-z]:', '')
        $unmappedTempPrefix = "Cannot detect source of '$containerTempBase/shared-ledger-dbtests-"
        $cliMountFailure =
            $cliText -match "invalid volume specification: '/:/:ro'" -or
            $cliText.IndexOf($unmappedTempPrefix, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if (-not $cliMountFailure) {
            throw "supabase test db failed with exit code $cliExitCode."
        }

        Write-Host 'Supabase CLI could not mount the test directory on this Windows host; rerunning via the same isolated project network with pg_prove.'
        $networkName = & docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{$name}}{{end}}' $containerName
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($networkName)) {
            throw "Could not resolve the network for isolated database container $containerName."
        }
        $testMountDir = Join-Path $testDir ''
        $volumeMount = "type=bind,source=$testMountDir,target=/tests,readonly"
        $containerTestPaths = $selectedTests | ForEach-Object {
            '/tests/' + [IO.Path]::GetFileName($_)
        }
        $pgProveArgs = @(
            'run', '--rm', '--network', $networkName,
            '--mount', $volumeMount,
            '--env', "PGPASSWORD=$dbPassword",
            '--env', 'PGOPTIONS=--search_path=extensions,public',
            'public.ecr.aws/supabase/pg_prove:3.36',
            'pg_prove', '--host', $containerName, '--port', '5432',
            '--username', $dbUser, '--dbname', $dbName
        ) + @($containerTestPaths)
        & docker @pgProveArgs
        if ($LASTEXITCODE -ne 0) { throw "pg_prove failed with exit code $LASTEXITCODE." }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($dbtestEnvPath -and (Test-Path -LiteralPath $dbtestEnvPath)) {
        Remove-Item -LiteralPath $dbtestEnvPath -Force
    }
    if ($isExistingProject) {
        Write-Host "Tests used existing isolated Supabase project at $isolatedRoot (project_id=$projectId); the stack was left running."
    }
    elseif ($KeepStack) {
        Write-Host "Isolated Supabase project retained at $isolatedRoot (project_id=$projectId)."
    }
    elseif ($stackPrepared) {
        & supabase stop --workdir $isolatedRoot --no-backup
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Could not stop isolated Supabase project; retained at $isolatedRoot."
        }
        else {
            $resolvedTemp = [IO.Path]::GetFullPath($tempBase).TrimEnd('\') + '\'
            $resolvedTarget = [IO.Path]::GetFullPath($isolatedRoot)
            if (-not $resolvedTarget.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -or
                [IO.Path]::GetFileName($resolvedTarget) -ne "shared-ledger-dbtests-$runId") {
                throw "Refusing recursive cleanup outside the generated isolated test directory: $resolvedTarget"
            }
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force
        }
    }
    else {
        $resolvedTemp = [IO.Path]::GetFullPath($tempBase).TrimEnd('\') + '\'
        $resolvedTarget = [IO.Path]::GetFullPath($isolatedRoot)
        if ($resolvedTarget.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase) -and
            [IO.Path]::GetFileName($resolvedTarget) -eq "shared-ledger-dbtests-$runId") {
            Remove-Item -LiteralPath $resolvedTarget -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
