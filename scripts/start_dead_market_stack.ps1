param(
    [switch]$RebuildDashboard
)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $root "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$pidsDir = Join-Path $runtimeDir "pids"
$dashboardDir = Join-Path $root "dashboard"
$dashboardStandaloneDir = Join-Path $dashboardDir ".next\\standalone"
$dashboardServerJs = Join-Path $dashboardStandaloneDir "server.js"
$cloudflaredConfig = Join-Path $HOME ".cloudflared\\config.yml"

New-Item -ItemType Directory -Force -Path $runtimeDir, $logsDir, $pidsDir | Out-Null

function Get-LiveProcessFromPidFile {
    param([string]$PidFile)

    if (!(Test-Path $PidFile)) {
        return $null
    }

    try {
        $pidValue = [int](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
    } catch {
        return $null
    }

    return Get-Process -Id $pidValue -ErrorAction SilentlyContinue
}

function Find-ProcessByCommandPattern {
    param([string]$Pattern)

    if (!$Pattern) {
        return $null
    }

    $processInfo = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like "*$Pattern*" } |
        Select-Object -First 1

    if (!$processInfo) {
        return $null
    }

    return Get-Process -Id $processInfo.ProcessId -ErrorAction SilentlyContinue
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$PidFile,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$StdOutLog,
        [string]$StdErrLog,
        [string]$ExistingProcessPattern = "",
        [hashtable]$EnvironmentVariables = @{}
    )

    $existing = Get-LiveProcessFromPidFile -PidFile $PidFile
    if ($existing -and $ExistingProcessPattern) {
        $existingProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($existing.Id)" -ErrorAction SilentlyContinue
        if (!$existingProcessInfo -or $existingProcessInfo.CommandLine -notlike "*$ExistingProcessPattern*") {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            $existing = $null
        }
    }
    if (!$existing) {
        $existing = Find-ProcessByCommandPattern -Pattern $ExistingProcessPattern
        if ($existing) {
            Set-Content -Path $PidFile -Value $existing.Id -Encoding ascii
        }
    }

    if ($existing) {
        Write-Host "$Name already running (PID $($existing.Id))"
        return $existing
    }

    if (Test-Path $StdOutLog) {
        Remove-Item $StdOutLog -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $StdErrLog) {
        Remove-Item $StdErrLog -Force -ErrorAction SilentlyContinue
    }

    $savedEnvironment = @{}
    foreach ($entry in $EnvironmentVariables.GetEnumerator()) {
        $savedEnvironment[$entry.Key] = [Environment]::GetEnvironmentVariable($entry.Key, "Process")
        [Environment]::SetEnvironmentVariable($entry.Key, [string]$entry.Value, "Process")
    }

    try {
        $process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $StdOutLog `
            -RedirectStandardError $StdErrLog `
            -WindowStyle Hidden `
            -PassThru
    } finally {
        foreach ($entry in $savedEnvironment.GetEnumerator()) {
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
        }
    }

    Set-Content -Path $PidFile -Value $process.Id -Encoding ascii
    Write-Host "Started $Name (PID $($process.Id))"
    return $process
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    return $false
}

function Test-DashboardBundle {
    param([string]$DashboardDir)

    $requiredPaths = @(
        (Join-Path $DashboardDir ".next\\BUILD_ID"),
        (Join-Path $DashboardDir ".next\\static"),
        (Join-Path $DashboardDir ".next\\standalone\\server.js"),
        (Join-Path $DashboardDir ".next\\standalone\\.next\\static")
    )

    foreach ($requiredPath in $requiredPaths) {
        if (!(Test-Path $requiredPath)) {
            return $false
        }
    }

    $appChunk = Get-ChildItem `
        -Path (Join-Path $DashboardDir ".next\\standalone\\.next\\static\\chunks\\app") `
        -Filter "*.js" `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    return $null -ne $appChunk
}

function Get-DashboardProbeChunkUrl {
    param([string]$DashboardDir)

    $staticRoot = Join-Path $DashboardDir ".next\\standalone\\.next\\static"
    $chunk = Get-ChildItem `
        -Path (Join-Path $staticRoot "chunks\\app") `
        -Filter "*.js" `
        -Recurse `
        -ErrorAction SilentlyContinue |
        Select-Object -First 1

    if (!$chunk) {
        return $null
    }

    $relativeChunkPath = ($chunk.FullName -replace '^.*[\\/]\.next[\\/]static[\\/]', '').Replace("\", "/")
    return "http://127.0.0.1:3000/_next/static/$relativeChunkPath"
}

function Get-DashboardProcess {
    param([string]$PidFile)

    $existing = Get-LiveProcessFromPidFile -PidFile $PidFile
    if ($existing -and $existing.ProcessName -eq "node") {
        return $existing
    }

    if ($existing) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    $listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$listener) {
        return $null
    }

    $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    if (!$owner -or $owner.ProcessName -ne "node") {
        return $null
    }

    $ownerInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($owner.Id)" -ErrorAction SilentlyContinue
    if (!$ownerInfo -or $ownerInfo.CommandLine -notlike "*server.js*") {
        return $null
    }

    Set-Content -Path $PidFile -Value $owner.Id -Encoding ascii
    return $owner
}

function Get-LatestSourceWriteTime {
    param([string[]]$Paths)

    $latest = [datetime]::MinValue
    foreach ($sourcePath in $Paths) {
        if (!(Test-Path $sourcePath)) {
            continue
        }

        $items = Get-ChildItem -Path $sourcePath -Recurse -File -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            if ($item.LastWriteTimeUtc -gt $latest) {
                $latest = $item.LastWriteTimeUtc
            }
        }
    }

    return $latest
}

if (!(Test-Path $cloudflaredConfig)) {
    throw "Cloudflare config was not found at $cloudflaredConfig"
}

$dashboardSourcePaths = @(
    (Join-Path $dashboardDir "app"),
    (Join-Path $dashboardDir "public"),
    (Join-Path $dashboardDir "package.json"),
    (Join-Path $dashboardDir "package-lock.json"),
    (Join-Path $dashboardDir "next.config.ts"),
    (Join-Path $dashboardDir "scripts")
)

$needsDashboardBuild = $RebuildDashboard -or !(Test-Path $dashboardServerJs)
if (!$needsDashboardBuild) {
    $latestSourceWriteTime = Get-LatestSourceWriteTime -Paths $dashboardSourcePaths
    $serverWriteTime = (Get-Item $dashboardServerJs).LastWriteTimeUtc
    if ($latestSourceWriteTime -gt $serverWriteTime) {
        $needsDashboardBuild = $true
    }
}

$dashboardPidFile = Join-Path $pidsDir "dashboard.pid"
$bridgePidFile = Join-Path $pidsDir "bridge.pid"
$botPidFile = Join-Path $pidsDir "bot.pid"
$tunnelPidFile = Join-Path $pidsDir "cloudflared.pid"

$dashboardStdOut = Join-Path $logsDir "dashboard.out.log"
$dashboardStdErr = Join-Path $logsDir "dashboard.err.log"
$bridgeStdOut = Join-Path $logsDir "bridge.out.log"
$bridgeStdErr = Join-Path $logsDir "bridge.err.log"
$botStdOut = Join-Path $logsDir "bot.out.log"
$botStdErr = Join-Path $logsDir "bot.err.log"
$tunnelStdOut = Join-Path $logsDir "cloudflared.out.log"
$tunnelStdErr = Join-Path $logsDir "cloudflared.err.log"

$dashboardExisting = Get-DashboardProcess -PidFile $dashboardPidFile

if ($needsDashboardBuild -and $dashboardExisting) {
    Write-Host "Stopping existing dashboard before rebuild..."
    Stop-Process -Id $dashboardExisting.Id -Force -ErrorAction SilentlyContinue
    Remove-Item $dashboardPidFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $dashboardExisting = $null
}

if ($needsDashboardBuild) {
    Write-Host "Building dashboard production bundle..."
    Push-Location $dashboardDir
    try {
        & npm.cmd run build | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Dashboard build failed."
        }
    } finally {
        Pop-Location
    }

    if (!(Test-DashboardBundle -DashboardDir $dashboardDir)) {
        throw "Dashboard build completed without required client assets."
    }
}

if (!$dashboardExisting) {
    $listener = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $owner = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $ownerName = if ($owner) { "$($owner.ProcessName) (PID $($owner.Id))" } else { "PID $($listener.OwningProcess)" }
        throw "Port 3000 is already in use by $ownerName. Stop the old server first."
    }
}

if ($dashboardExisting) {
    Set-Content -Path $dashboardPidFile -Value $dashboardExisting.Id -Encoding ascii
    Write-Host "Dashboard already running (PID $($dashboardExisting.Id))"
} else {
    Remove-Item $dashboardPidFile -Force -ErrorAction SilentlyContinue
    Start-ManagedProcess `
        -Name "Dashboard" `
        -PidFile $dashboardPidFile `
        -FilePath "node" `
        -Arguments @("server.js") `
        -WorkingDirectory $dashboardStandaloneDir `
        -StdOutLog $dashboardStdOut `
        -StdErrLog $dashboardStdErr `
        -EnvironmentVariables @{
            HOSTNAME = "127.0.0.1"
            PORT = "3000"
            NODE_ENV = "production"
        } | Out-Null
}

if (!(Wait-HttpOk -Url "http://127.0.0.1:3000" -TimeoutSeconds 60)) {
    throw "Dashboard did not become ready on http://127.0.0.1:3000"
}

$dashboardProbeChunkUrl = Get-DashboardProbeChunkUrl -DashboardDir $dashboardDir
if ($dashboardProbeChunkUrl -and !(Wait-HttpOk -Url $dashboardProbeChunkUrl -TimeoutSeconds 60)) {
    throw "Dashboard root responded, but client chunk was not available at $dashboardProbeChunkUrl"
}

Start-ManagedProcess `
    -Name "Dashboard Bridge" `
    -PidFile $bridgePidFile `
    -FilePath "python" `
    -Arguments @("-u", "dashboard_live_bridge.py", "--env-file", ".env", "--interval-seconds", "20", "watch") `
    -WorkingDirectory $root `
    -StdOutLog $bridgeStdOut `
    -StdErrLog $bridgeStdErr `
    -ExistingProcessPattern "dashboard_live_bridge.py --env-file .env" | Out-Null

Start-ManagedProcess `
    -Name "Live Bot" `
    -PidFile $botPidFile `
    -FilePath "python" `
    -Arguments @("-u", "main.py", "--env-file", ".env", "live") `
    -WorkingDirectory $root `
    -StdOutLog $botStdOut `
    -StdErrLog $botStdErr `
    -ExistingProcessPattern "main.py --env-file .env live" | Out-Null

Start-ManagedProcess `
    -Name "Cloudflare Tunnel" `
    -PidFile $tunnelPidFile `
    -FilePath "cloudflared" `
    -Arguments @("--no-autoupdate", "tunnel", "run", "dead-market-dashboard") `
    -WorkingDirectory $root `
    -StdOutLog $tunnelStdOut `
    -StdErrLog $tunnelStdErr `
    -ExistingProcessPattern "tunnel run dead-market-dashboard" | Out-Null

Write-Host ""
Write-Host "Dead Market live stack is up."
Write-Host "Local dashboard: http://127.0.0.1:3000"
Write-Host "Public dashboard: https://app.dead-market.com"
Write-Host "Logs: $logsDir"
