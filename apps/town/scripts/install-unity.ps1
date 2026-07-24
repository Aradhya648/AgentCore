# Install Unity 6 LTS (6000.0.78f1) + WebGL Build Support on Windows.
#
# Mode A (recommended in CN): offline sideload
#   1. On an unblocked network, download the two installers into:
#        C:\Temp\agenttown-unity-install\
#   2. Run:  pwsh -File apps/town/scripts/install-unity.ps1 -LocalOnly
#
# Mode B: online download (needs US/EU exit; HK/JP usually still blocked)
#   pwsh -File apps/town/scripts/install-unity.ps1 [-ProxyPort 7897]
#
# Overseas download one-liner (bash):
#   curl -fLO 'https://download.unity3d.com/download_unity/ec8a99a872be/Windows64EditorInstaller/UnitySetup64-6000.0.78f1.exe'
#   curl -fLO 'https://download.unity3d.com/download_unity/ec8a99a872be/TargetSupportInstaller/UnitySetup-WebGL-Support-for-Editor-6000.0.78f1.exe'

param(
    [string]$Version = '6000.0.78f1',
    [string]$Changeset = 'ec8a99a872be',
    [string]$LocalDir = 'C:\Temp\agenttown-unity-install',
    [switch]$LocalOnly,
    [int]$ProxyPort = 0
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) { Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "OK $msg" -ForegroundColor Green }
function Write-Err([string]$msg) { Write-Host $msg -ForegroundColor Red }

$editorName = "UnitySetup64-$Version.exe"
$webglName = "UnitySetup-WebGL-Support-for-Editor-$Version.exe"
$editorUrl = "https://download.unity3d.com/download_unity/$Changeset/Windows64EditorInstaller/$editorName"
$webglUrl = "https://download.unity3d.com/download_unity/$Changeset/TargetSupportInstaller/$webglName"
$installRoot = "C:\Program Files\Unity\Hub\Editor\$Version"

New-Item -ItemType Directory -Force -Path $LocalDir | Out-Null

function Resolve-InstallerPath {
    param([string]$Dir, [string]$ExpectedName, [string]$Pattern, [int64]$MinBytes)
    $exact = Join-Path $Dir $ExpectedName
    if ((Test-Path $exact) -and ((Get-Item $exact).Length -ge $MinBytes)) {
        return $exact
    }
    $hit = Get-ChildItem -Path $Dir -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like $Pattern -and $_.Length -ge $MinBytes } |
        Sort-Object Length -Descending |
        Select-Object -First 1
    if ($hit) { return $hit.FullName }
    return $null
}

function Show-SideloadHelp {
    Write-Err @"

Offline sideload: place both installers in:
  $LocalDir

Required files:
  $editorName          (~3.8 GB)
  $webglName  (~150 MB)

Download on an unblocked network (US/EU VPS, friend abroad, etc.):
  $editorUrl
  $webglUrl

Then re-run:
  pwsh -File apps/town/scripts/install-unity.ps1 -LocalOnly
"@
}

function Get-CurlProxyArg {
    param([int]$Port)
    if ($Port -gt 0) { return @('-x', "http://127.0.0.1:$Port") }
    return @()
}

function Test-UnityDownload {
    param([string]$Url, [int]$Port)
    $proxy = Get-CurlProxyArg -Port $Port
    $out = & curl.exe @proxy -sL -o NUL -w "%{http_code} %{size_download} %{url_effective}" -r 0-1048575 --max-time 45 $Url 2>&1
    $parts = $out -split ' ', 3
    $code = $parts[0]
    $bytes = [int64]$parts[1]
    $final = $parts[2]
    $ok = ($code -eq '200' -or $code -eq '206') -and $bytes -gt 1000000 -and ($final -notmatch 'unitychina\.cn')
    [pscustomobject]@{ Ok = $ok; Code = $code; Bytes = $bytes; Final = $final }
}

function Find-OpenProxyPort {
    foreach ($p in @(7897, 7890, 12001, 10808, 10809)) {
        $t = Test-NetConnection 127.0.0.1 -Port $p -WarningAction SilentlyContinue
        if ($t.TcpTestSucceeded) { return $p }
    }
    return 0
}

function Download-File {
    param([string]$Url, [string]$Dest, [int]$Port)
    $proxy = Get-CurlProxyArg -Port $Port
    Write-Step "Downloading $(Split-Path $Dest -Leaf)..."
    & curl.exe @proxy -fL --retry 5 --retry-delay 3 -C - -o $Dest $Url
    if ($LASTEXITCODE -ne 0) { throw "curl failed for $Url" }
}

$editorExe = Resolve-InstallerPath -Dir $LocalDir -ExpectedName $editorName -Pattern 'UnitySetup64-*.exe' -MinBytes 3000000000
$webglExe = Resolve-InstallerPath -Dir $LocalDir -ExpectedName $webglName -Pattern 'UnitySetup-WebGL*.exe' -MinBytes 50000000

if ($editorExe -and $webglExe) {
    Write-Ok "Using local installers:"
    Write-Host "  Editor: $($editorExe) ($([math]::Round((Get-Item $editorExe).Length/1GB, 2)) GB)"
    Write-Host "  WebGL:  $($webglExe) ($([math]::Round((Get-Item $webglExe).Length/1MB, 1)) MB)"
}
elseif ($LocalOnly) {
    Show-SideloadHelp
    exit 1
}
else {
  Write-Step "Local installers not found; trying online download..."
  if ($ProxyPort -le 0) { $ProxyPort = Find-OpenProxyPort }

  $probe = Test-UnityDownload -Url $editorUrl -Port $ProxyPort
  if (-not $probe.Ok) {
      Write-Err "Online download blocked (HTTP $($probe.Code), final=$($probe.Final))."
      Show-SideloadHelp
      exit 1
  }
  Write-Ok "Download path OK ($($probe.Bytes) bytes probed)"

  $editorExe = Join-Path $LocalDir $editorName
  $webglExe = Join-Path $LocalDir $webglName
  Download-File -Url $editorUrl -Dest $editorExe -Port $ProxyPort
  Download-File -Url $webglUrl -Dest $webglExe -Port $ProxyPort
}

if (Test-Path $installRoot) {
    Write-Ok "Unity $Version already installed at $installRoot — skipping editor install."
}
else {
    Write-Step "Installing Unity Editor (silent, UAC prompt expected)..."
    $editorArgs = @('/S', "/D=$installRoot")
    $p = Start-Process -FilePath $editorExe -ArgumentList $editorArgs -Wait -PassThru -Verb RunAs
    if ($p.ExitCode -ne 0) { throw "Editor installer exit $($p.ExitCode)" }
}

$webglMarker = Join-Path $installRoot 'Editor\Data\PlaybackEngines\WebGLSupport'
if (Test-Path $webglMarker) {
    Write-Ok 'WebGL Build Support already present — skipping.'
}
else {
    Write-Step 'Installing WebGL Build Support (silent, UAC prompt expected)...'
    $p2 = Start-Process -FilePath $webglExe -ArgumentList '/S' -Wait -PassThru -Verb RunAs
    if ($p2.ExitCode -ne 0) { throw "WebGL installer exit $($p2.ExitCode)" }
}

$hub = 'C:\Program Files\Unity Hub\Unity Hub.exe'
if (Test-Path $hub) {
    Write-Step 'Registering editor with Unity Hub...'
    & $hub -- --headless editors --installPath $installRoot 2>&1 | Out-Null
}

Write-Ok "Unity $Version + WebGL ready at $installRoot"
Write-Host 'Next: open apps/town in Hub, follow apps/town/EDITOR-WIRING.md'
