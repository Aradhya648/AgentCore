# Open AgentTown Unity project in the Editor (bypasses Hub when Hub click is unresponsive).
# Usage: powershell -File apps/town/scripts/open-unity.ps1

param(
    [string]$Version = '6000.0.78f1',
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'

function Get-UnityExe {
    param([string]$Ver)
    $candidates = @(
        "C:\Program Files\Unity\Hub\Editor\$Ver\Editor\Unity.exe",
        "C:\Program Files\Unity\Hub\Editor\$Ver-x86_64\Editor\Unity.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    throw "Unity $Ver not found."
}

# Stale batchmode instances lock the project and make Hub clicks appear to do nothing.
Get-Process -Name 'Unity' -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -eq '' } |
    ForEach-Object {
        Write-Host "Stopping headless Unity (pid $($_.Id)) that is locking the project..."
        Stop-Process -Id $_.Id -Force
    }

Start-Sleep -Seconds 2

$unity = Get-UnityExe -Ver $Version
Write-Host "Opening $ProjectPath with $unity"
Start-Process $unity -ArgumentList "-projectPath `"$ProjectPath`""
