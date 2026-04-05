$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidsDir = Join-Path $root "runtime\\pids"

function Stop-ManagedProcess {
    param(
        [string]$Name,
        [string]$PidFile,
        [string]$CommandPattern = "",
        [int]$Port = 0
    )

    if ($Port -gt 0) {
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($listener) {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped $Name (PID $($listener.OwningProcess))"
            return
        }
    }

    if (!(Test-Path $PidFile)) {
        if ($CommandPattern) {
            $fallback = Get-CimInstance Win32_Process |
                Where-Object { $_.CommandLine -like "*$CommandPattern*" } |
                Select-Object -ExpandProperty ProcessId

            if ($fallback) {
                foreach ($pidValue in $fallback) {
                    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
                    Write-Host "Stopped $Name (PID $pidValue)"
                }
            } else {
                Write-Host "$Name is not running"
            }
            return
        }

        Write-Host "$Name is not running"
        return
    }

    try {
        $pidValue = [int](Get-Content $PidFile -ErrorAction Stop | Select-Object -First 1)
    } catch {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "$Name pid file was invalid"
        return
    }

    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Name (PID $pidValue)"
    } else {
        Write-Host "$Name was already stopped"
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Stop-ManagedProcess -Name "Cloudflare Tunnel" -PidFile (Join-Path $pidsDir "cloudflared.pid") -CommandPattern "tunnel run dead-market-dashboard"
Stop-ManagedProcess -Name "Live Bot" -PidFile (Join-Path $pidsDir "bot.pid") -CommandPattern "main.py --env-file .env live"
Stop-ManagedProcess -Name "Dashboard Bridge" -PidFile (Join-Path $pidsDir "bridge.pid") -CommandPattern "dashboard_live_bridge.py --env-file .env"
Stop-ManagedProcess -Name "Dashboard" -PidFile (Join-Path $pidsDir "dashboard.pid") -CommandPattern "server.js" -Port 3000
