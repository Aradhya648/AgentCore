# One-shot Unity project verify: setup + EditMode tests + Play smoke.
# Usage: pwsh apps/town/scripts/verify-unity.ps1
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

function Invoke-UnityBatch {
    param(
        [string]$Unity,
        [string]$Project,
        [string]$LogFile,
        [string[]]$ExtraArgs,
        [switch]$NoQuit,
        [string]$WaitLogPattern,
        [int]$WaitTimeoutSec = 180
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
    if (Test-Path $LogFile) { Remove-Item -Force $LogFile }

    # Avoid PowerShell automatic $args; put ExtraArgs before -quit so -runTests is not skipped.
    $unityArgs = @(
        '-batchmode', '-nographics',
        '-projectPath', $Project,
        '-logFile', $LogFile
    )
    if ($null -ne $ExtraArgs -and $ExtraArgs.Count -gt 0) {
        $unityArgs += $ExtraArgs
    }
    $isRunTests = $ExtraArgs -contains '-runTests'
    # Test Framework exits on its own; -quit before/with -runTests can skip the runner.
    if (-not $NoQuit -and -not $isRunTests) {
        $unityArgs += '-quit'
    }

    Write-Host "> `"$Unity`" $($unityArgs -join ' ')"

    if ($NoQuit) {
        # Play smoke: Unity CLI may return before EnterPlaymode finishes. Keep the process
        # alive until the success/failure log appears (or timeout), then wait for full exit.
        $proc = Start-Process -FilePath $Unity -ArgumentList $unityArgs -PassThru
        $deadline = (Get-Date).AddSeconds($WaitTimeoutSec)
        $matched = $false
        while ((Get-Date) -lt $deadline) {
            if ($WaitLogPattern -and (Test-LogMatches -LogFile $LogFile -Pattern $WaitLogPattern)) {
                $matched = $true
                break
            }
            if ($proc.HasExited -and -not $WaitLogPattern) { break }
            if ($proc.HasExited -and $WaitLogPattern -and (Test-LogMatches -LogFile $LogFile -Pattern $WaitLogPattern)) {
                $matched = $true
                break
            }
            Start-Sleep -Seconds 1
        }

        if (-not $matched -and $WaitLogPattern) {
            Get-Process -Name 'Unity' -ErrorAction SilentlyContinue |
                Where-Object { $_.MainWindowTitle -eq '' } |
                Stop-Process -Force -ErrorAction SilentlyContinue
            Wait-UnityExit -TimeoutSec 30
            throw "Timed out waiting for log pattern '$WaitLogPattern' in $LogFile"
        }

        # Give batch code a moment to call EditorApplication.Exit, then ensure exit.
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
        return $LogFile
    }

    & $Unity @unityArgs
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 0 }

    if (Test-Path $LogFile) {
        $tail = Get-Content $LogFile -Tail 80 -ErrorAction SilentlyContinue
        $rcLine = $tail | Where-Object { $_ -match 'return code (\d+)' } | Select-Object -Last 1
        if ($rcLine -match 'return code (\d+)') {
            $code = [int]$Matches[1]
        }
    }

    # Wait until the previous batch Unity has fully exited before the next step.
    Wait-UnityExit -TimeoutSec 60

    if ($code -ne 0) {
        $tail = @()
        if (Test-Path $LogFile) {
            $tail = Get-Content $LogFile -Tail 40 -ErrorAction SilentlyContinue
        }
        throw "Unity exited $code. Log: $LogFile`n$($tail -join "`n")"
    }

    return $LogFile
}

function Assert-LogContains {
    param(
        [string]$LogFile,
        [string]$Pattern,
        [string]$StepName,
        [int]$TimeoutSec = 120
    )
    for ($i = 0; $i -lt $TimeoutSec; $i++) {
        if (Test-LogMatches -LogFile $LogFile -Pattern $Pattern) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "${StepName} failed — expected log pattern '$Pattern' in $LogFile"
}

$unity = Get-UnityExe -Ver $Version
$logDir = Join-Path $ProjectPath 'logs'
$results = Join-Path $logDir 'editmode-results.xml'

if (Get-Process -Name 'Unity' -ErrorAction SilentlyContinue) {
    Write-Err 'Unity Editor is open. Close it, then re-run this script.'
    exit 2
}

Write-Step '1/3 Project setup (URP + Town.unity + Bootstrap HUD refs)'
$setupLog = Invoke-UnityBatch -Unity $unity -Project $ProjectPath -LogFile (Join-Path $logDir 'verify-setup.log') -ExtraArgs @(
    '-executeMethod', 'AgentTown.Editor.AgentTownProjectSetup.SetupFromBatch'
)
Assert-LogContains -LogFile $setupLog -Pattern '\[AgentTown\] Project setup complete' -StepName 'Setup'
Write-Ok 'Setup complete'

Write-Step '2/3 EditMode tests'
# Drop stale results so a failed/skipped write cannot leave a previous run's XML.
if (Test-Path $results) { Remove-Item -Force $results }
$testLog = Invoke-UnityBatch -Unity $unity -Project $ProjectPath -LogFile (Join-Path $logDir 'verify-tests.log') -ExtraArgs @(
    '-runTests', '-testPlatform', 'editmode',
    '-assemblyNames', 'AgentTown.EditModeTests',
    '-testResults', $results
)
if (-not (Test-Path $results)) {
    throw "Missing test results: $results"
}
# Guard against Unity exiting without rewriting results (mtime must be from this run).
$resultsAgeSec = ((Get-Date) - (Get-Item $results).LastWriteTime).TotalSeconds
if ($resultsAgeSec -gt 120) {
    throw "Stale test results ($([int]$resultsAgeSec)s old): $results — Unity did not rewrite the file"
}
[xml]$xml = Get-Content $results
$total = [int]$xml.'test-run'.total
$passed = [int]$xml.'test-run'.passed
$failed = [int]$xml.'test-run'.failed
if ($failed -gt 0) {
    throw "EditMode tests failed: $failed failed, $passed passed (of $total)"
}
Write-Ok "EditMode tests: $passed/$total passed"

Write-Step '3/3 Play smoke (runtime town spawn)'
$playPattern = 'Play smoke PASSED|NavMesh baked over town ground|Play smoke FAILED'
$playLog = Invoke-UnityBatch -Unity $unity -Project $ProjectPath -LogFile (Join-Path $logDir 'verify-play.log') -NoQuit `
    -WaitLogPattern $playPattern -WaitTimeoutSec 240 -ExtraArgs @(
    '-executeMethod', 'AgentTown.Editor.AgentTownBatchVerify.RunPlaySmokeFromBatch'
)
if (Test-LogMatches -LogFile $playLog -Pattern 'Play smoke FAILED') {
    throw "Play smoke FAILED. Log: $playLog"
}
Assert-LogContains -LogFile $playLog -Pattern 'Play smoke PASSED|NavMesh baked over town ground' -StepName 'Play smoke' -TimeoutSec 5
Write-Ok 'Play smoke passed'

Write-Host ''
Write-Ok 'AgentTown Unity project verified end-to-end.'
Write-Host 'Open Hub → town → Play Assets/Scenes/Town.unity' -ForegroundColor Yellow
exit 0
