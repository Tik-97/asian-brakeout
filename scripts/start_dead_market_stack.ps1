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
        [string]$ExistingProcessPattern = ""
    )

    $existing = Get-LiveProcessFromPidFile -PidFile $PidFile
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

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdOutLog `
        -RedirectStandardError $StdErrLog `
        -WindowStyle Hidden `
        -PassThru

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

if (!(Test-Path $cloudflaredConfig)) {
    throw "Cloudflare config was not found at $cloudflaredConfig"
}

if ($RebuildDashboard -or !(Test-Path $dashboardServerJs)) {
    Write-Host "Building dashboard production bundle..."
    & npm.cmd run build | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Dashboard build failed."
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

$dashboardPatterns = @(
    "server.js",
    "next\\dist\\bin\\next*start --hostname 127.0.0.1 --port 3000"
)

$dashboardExisting = $null
foreach ($pattern in $dashboardPatterns) {
    $dashboardExisting = Find-ProcessByCommandPattern -Pattern $pattern
    if ($dashboardExisting) {
        break
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

$dashboardCommand = "`$env:HOSTNAME='127.0.0.1'; `$env:PORT='3000'; `$env:NODE_ENV='production'; Set-Location '$dashboardStandaloneDir'; node server.js"
if ($dashboardExisting) {
    Set-Content -Path $dashboardPidFile -Value $dashboardExisting.Id -Encoding ascii
    Write-Host "Dashboard already running (PID $($dashboardExisting.Id))"
} else {
    Start-ManagedProcess `
        -Name "Dashboard" `
        -PidFile $dashboardPidFile `
        -FilePath "powershell.exe" `
        -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $dashboardCommand) `
        -WorkingDirectory $dashboardStandaloneDir `
        -StdOutLog $dashboardStdOut `
        -StdErrLog $dashboardStdErr `
        -ExistingProcessPattern "dashboard\\.next\\standalone\\server.js" | Out-Null
}

if (!(Wait-HttpOk -Url "http://127.0.0.1:3000" -TimeoutSeconds 60)) {
    throw "Dashboard did not become ready on http://127.0.0.1:3000"
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
