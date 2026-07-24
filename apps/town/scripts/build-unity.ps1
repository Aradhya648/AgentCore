# Build AgentTown Unity player (Windows and/or WebGL).
# Usage:
#   pwsh apps/town/scripts/build-unity.ps1
#   pwsh apps/town/scripts/build-unity.ps1 -Target WebGL
#   pwsh apps/town/scripts/build-unity.ps1 -Target All
# Close the Unity Editor before running (single-instance lock).

param(
    [ValidateSet('Windows', 'WebGL', 'All')]
    [string]$Target = 'Windows',
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

function Invoke-UnityBuild {
    param(
        [string]$Unity,
        [string]$Project,
        [string]$Method,
        [string]$LogFile
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
    $args = @(
        '-batchmode', '-nographics', '-quit',
        '-projectPath', $Project,
        '-logFile', $LogFile,
        '-executeMethod', $Method
    )
    Write-Host "> `"$Unity`" $($args -join ' ')"
    # Unity Hub/Editor sometimes returns from the launcher process while a child
    # Editor keeps running. Wait on the log footer instead of process exit alone.
    if (Test-Path $LogFile) { Remove-Item $LogFile -Force -ErrorAction SilentlyContinue }
    $p = Start-Process -FilePath $Unity -ArgumentList $args -PassThru -NoNewWindow
    $deadline = (Get-Date).AddMinutes(45)
    $done = $false
    $code = 1
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-Path $LogFile) {
            $tail = Get-Content $LogFile -Tail 40 -ErrorAction SilentlyContinue
            $joined = ($tail -join "`n")
            if ($joined -match 'Exiting batchmode successfully now!' -or
                $joined -match 'Application will terminate with return code 0') {
                $done = $true
                $code = 0
                break
            }
            if ($joined -match 'return code ([1-9]\d*)' -or
                $joined -match 'Build .* failed' -or
                $joined -match 'executeMethod .* threw') {
                if ($joined -match 'return code (\d+)') { $code = [int]$Matches[1] }
                $done = $true
                break
            }
        }
        # Still running?
        $alive = Get-Process -Id $p.Id -ErrorAction SilentlyContinue
        $anyUnity = Get-Process -Name 'Unity' -ErrorAction SilentlyContinue
        if (-not $alive -and -not $anyUnity) {
            Start-Sleep -Seconds 2
            if (Test-Path $LogFile) {
                $tail = Get-Content $LogFile -Tail 40 -ErrorAction SilentlyContinue
                $joined = ($tail -join "`n")
                if ($joined -match 'Build .* OK' -or $joined -match 'Build Finished, Result: Success') {
                    $code = 0
                } elseif ($joined -match 'return code (\d+)') {
                    $code = [int]$Matches[1]
                } else {
                    $code = if ($null -ne $p.ExitCode) { $p.ExitCode } else { 1 }
                }
            }
            $done = $true
            break
        }
    }
    if (-not $done) {
        throw "Timed out waiting for Unity ($Method). Log: $LogFile"
    }
    Start-Sleep -Seconds 2

    if ($code -ne 0) {
        $tail = @()
        if (Test-Path $LogFile) { $tail = Get-Content $LogFile -Tail 50 }
        throw "Unity exited $code ($Method). Log: $LogFile`n$($tail -join "`n")"
    }
}

if (Get-Process -Name 'Unity' -ErrorAction SilentlyContinue) {
    Write-Err 'Unity Editor is open. Close it, then re-run this script.'
    exit 2
}

$unity = Get-UnityExe -Ver $Version
$logDir = Join-Path $ProjectPath 'logs'
$targets = @()
if ($Target -eq 'All') { $targets = @('Windows', 'WebGL') } else { $targets = @($Target) }

foreach ($t in $targets) {
    if ($t -eq 'Windows') {
        Write-Step 'Build Windows Standalone'
        Invoke-UnityBuild -Unity $unity -Project $ProjectPath `
            -Method 'AgentTown.Editor.AgentTownBuild.BuildWindows' `
            -LogFile (Join-Path $logDir 'build-windows.log')
        $exe = Join-Path $ProjectPath 'Builds\Windows\AgentTown.exe'
        if (-not (Test-Path $exe)) { throw "Missing output: $exe" }
        Write-Ok "Windows → $exe"
    }
    elseif ($t -eq 'WebGL') {
        Write-Step 'Build WebGL'
        Invoke-UnityBuild -Unity $unity -Project $ProjectPath `
            -Method 'AgentTown.Editor.AgentTownBuild.BuildWebGL' `
            -LogFile (Join-Path $logDir 'build-webgl.log')
        $index = Join-Path $ProjectPath 'Builds\WebGL\index.html'
        if (-not (Test-Path $index)) { throw "Missing output: $index" }
        Write-Ok "WebGL → $(Split-Path $index)"
    }
}

Write-Ok "Done ($($targets -join ', '))"
