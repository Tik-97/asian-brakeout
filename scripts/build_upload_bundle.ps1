param(
    [string]$OutputRoot = (Join-Path (Join-Path $PSScriptRoot "..") "dist"),
    [string]$BundleName = "asian-breakout-upload",
    [switch]$IncludeRuntimeState
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$outputRootPath = [System.IO.Path]::GetFullPath($OutputRoot)
$bundleDir = Join-Path $outputRootPath $BundleName
$zipPath = Join-Path $outputRootPath ("{0}.zip" -f $BundleName)

function Copy-IfExists {
    param(
        [string]$SourcePath,
        [string]$DestinationPath
    )

    if (Test-Path -LiteralPath $SourcePath) {
        $parent = Split-Path -Path $DestinationPath -Parent
        if ($parent) {
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
        }
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Recurse -Force
    }
}

if (Test-Path -LiteralPath $bundleDir) {
    Remove-Item -LiteralPath $bundleDir -Recurse -Force
}

New-Item -ItemType Directory -Path $outputRootPath -Force | Out-Null
New-Item -ItemType Directory -Path $bundleDir -Force | Out-Null

if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

$rootFiles = @(
    ".env",
    ".env.example",
    ".dockerignore",
    "Dockerfile",
    "docker-compose.yml",
    "DOCKER_DEPLOY.md",
    "requirements.txt",
    "README.md"
)

foreach ($file in $rootFiles) {
    Copy-IfExists -SourcePath (Join-Path $repoRoot $file) -DestinationPath (Join-Path $bundleDir $file)
}

Get-ChildItem -LiteralPath $repoRoot -File -Filter "*.py" | ForEach-Object {
    Copy-IfExists -SourcePath $_.FullName -DestinationPath (Join-Path $bundleDir $_.Name)
}

$rootDirs = @("scripts", "cloudflare")
foreach ($dir in $rootDirs) {
    Copy-IfExists -SourcePath (Join-Path $repoRoot $dir) -DestinationPath (Join-Path $bundleDir $dir)
}

$dashboardSource = Join-Path $repoRoot "dashboard"
$dashboardTarget = Join-Path $bundleDir "dashboard"
New-Item -ItemType Directory -Path $dashboardTarget -Force | Out-Null

$dashboardDirs = @(
    "app",
    "public",
    "scripts"
)

foreach ($dir in $dashboardDirs) {
    Copy-IfExists -SourcePath (Join-Path $dashboardSource $dir) -DestinationPath (Join-Path $dashboardTarget $dir)
}

$dashboardFiles = @(
    ".dockerignore",
    ".gitignore",
    "Dockerfile",
    "live-layout.css",
    "manual_withdrawals.json",
    "next-env.d.ts",
    "next.config.ts",
    "package-lock.json",
    "package.json",
    "README.md",
    "tsconfig.json"
)

foreach ($file in $dashboardFiles) {
    Copy-IfExists -SourcePath (Join-Path $dashboardSource $file) -DestinationPath (Join-Path $dashboardTarget $file)
}

if ($IncludeRuntimeState) {
    $runtimeTarget = Join-Path $bundleDir "runtime"
    New-Item -ItemType Directory -Path (Join-Path $runtimeTarget "dashboard") -Force | Out-Null

    $runtimeFiles = @(
        @{ Source = "state.json"; Destination = "state.json" },
        @{ Source = "order_audit.jsonl"; Destination = "order_audit.jsonl" },
        @{ Source = "runtime_state.json"; Destination = "runtime_state.json" }
    )

    foreach ($file in $runtimeFiles) {
        Copy-IfExists `
            -SourcePath (Join-Path $repoRoot $file.Source) `
            -DestinationPath (Join-Path $runtimeTarget $file.Destination)
    }

    Copy-IfExists `
        -SourcePath (Join-Path $dashboardSource "manual_withdrawals.json") `
        -DestinationPath (Join-Path $runtimeTarget "dashboard\\manual_withdrawals.json")
}

Push-Location $bundleDir
try {
    Compress-Archive -Path * -DestinationPath $zipPath -Force
}
finally {
    Pop-Location
}

$bundleSize = (Get-ChildItem -LiteralPath $bundleDir -Recurse -File -Force | Measure-Object Length -Sum).Sum
$zipSize = (Get-Item -LiteralPath $zipPath).Length

Write-Output ("Bundle folder: {0}" -f $bundleDir)
Write-Output ("Zip file: {0}" -f $zipPath)
Write-Output ("Bundle size: {0:N2} MB" -f ($bundleSize / 1MB))
Write-Output ("Zip size: {0:N2} MB" -f ($zipSize / 1MB))
