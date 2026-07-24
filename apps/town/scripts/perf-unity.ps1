# Graphics-enabled Unity FPS gate: 10 NPC watch floor (UT-16 / FE-19 "≥30 FPS").
# Usage: pwsh apps/town/scripts/perf-unity.ps1
# Runs WITHOUT -nographics on purpose: -nographics has no GPU, so an FPS number there would be
# a fake gate. Needs a real GPU/session (run on the dev machine, not a headless CI box).
# Close the Unity Editor before running (single-instance lock).

param(
    [string]$Version = '6000.0.78f1',
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) { Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "OK $msg" -ForegroundColor Green }
function Write-Err([string]$msg) { Write-Host $msg -ForegroundColor Red }

function Get-UnityExe {
    param([string]$Ver)
    $candidates = @(
        "C:\Program Files\Unity\Hub\Editor\$Ver\Editor\Unity.exe",
        "C:\Program Files\Unity\Hub\Editor\$Ver-x86_64\Editor\Unity.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    throw "Unity $Ver not found. Run: pwsh apps/town/scripts/install-unity.ps1 -LocalOnly"
}

function Test-LogMatches {
    param([string]$LogFile, [string]$Pattern)
    if (-not (Test-Path $LogFile)) { return $false }
    try {
        $raw = Get-Content -LiteralPath $LogFile -Raw -ErrorAction Stop
        return [bool]($raw -match $Pattern)
    } catch {
        return $false
    }
}

function Wait-UnityExit {
    param([int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (Get-Process -Name 'Unity' -ErrorAction SilentlyContinue) {
        if ((Get-Date) -ge $deadline) {
            throw "Timed out waiting for Unity to exit (${TimeoutSec}s). Close any Unity instance and re-run."
        }
        Start-Sleep -Seconds 1
    }
}

$unity = Get-UnityExe -Ver $Version
$logDir = Join-Path $ProjectPath 'logs'
$logFile = Join-Path $logDir 'perf-gate.log'

if (Get-Process -Name 'Unity' -ErrorAction SilentlyContinue) {
    Write-Err 'Unity Editor is open. Close it, then re-run this script.'
    exit 2
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
if (Test-Path $logFile) { Remove-Item -Force $logFile }

# NOTE: deliberately NO -nographics so the render loop actually runs.
$unityArgs = @(
    '-batchmode',
    '-projectPath', $ProjectPath,
    '-logFile', $logFile,
    '-executeMethod', 'AgentTown.Editor.AgentTownPerfGate.RunFromBatch'
)

Write-Step 'Play-mode FPS gate (graphics on, 10 NPC watch floor)'
Write-Host "> `"$unity`" $($unityArgs -join ' ')"

$verdictPattern = 'Perf gate PASSED|Perf gate FAILED'
$proc = Start-Process -FilePath $unity -ArgumentList $unityArgs -PassThru
$deadline = (Get-Date).AddSeconds(300)
$matched = $false
while ((Get-Date) -lt $deadline) {
    if (Test-LogMatches -LogFile $logFile -Pattern $verdictPattern) {
        $matched = $true
        break
    }
    if ($proc.HasExited -and (Test-LogMatches -LogFile $logFile -Pattern $verdictPattern)) {
        $matched = $true
        break
    }
    if ($proc.HasExited) { break }
    Start-Sleep -Seconds 2
}

# Let the editor call EditorApplication.Exit, then ensure the process is gone.
$exitDeadline = (Get-Date).AddSeconds(60)
while (-not $proc.HasExited -and (Get-Date) -lt $exitDeadline) {
    Start-Sleep -Seconds 1
}
if (-not $proc.HasExited) {
    Get-Process -Name 'Unity' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -eq '' } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}
Wait-UnityExit -TimeoutSec 60

$resultLine = $null
if (Test-Path $logFile) {
    $resultLine = Get-Content $logFile -ErrorAction SilentlyContinue |
        Where-Object { $_ -match 'Perf gate result:' } | Select-Object -Last 1
}
if ($resultLine) { Write-Host $resultLine -ForegroundColor Yellow }

if (-not $matched) {
    $tail = @()
    if (Test-Path $logFile) { $tail = Get-Content $logFile -Tail 40 -ErrorAction SilentlyContinue }
    throw "Perf gate produced no verdict. Log: $logFile`n$($tail -join "`n")"
}

if (Test-LogMatches -LogFile $logFile -Pattern 'Perf gate FAILED') {
    $failLine = Get-Content $logFile -ErrorAction SilentlyContinue |
        Where-Object { $_ -match 'Perf gate FAILED' } | Select-Object -Last 1
    throw "Perf gate FAILED. $failLine`nLog: $logFile"
}

Write-Ok 'Perf gate passed (10 NPC ≥ 30 FPS floor).'
exit 0
