# Phase 0 WebGL SSE connectivity spike (AgentTown §15.2).
#
# Step A (always): browser-path probe — login Bearer → create run → fetch SSE stream
#   from a page origin on :8080 or :4173 (CORS + SSE ReadableStream, same stack as jslib).
# Step B: if Builds/WebGL exists (or -Build), note the artifact.
# Step C (when WebGL present and not -SkipServe): serve static host, print one-click URL,
#   optionally -OpenBrowser, and Playwright jslib smoke (fetch tee; Unity HUD is not console).
#
# Usage:
#   pnpm town:spike:webgl
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1 -Build
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1 -OpenBrowser
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1 -SkipJslibSmoke -OpenBrowser
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1 -SkipServe
#   powershell -File apps/town/scripts/spike-webgl-sse.ps1 -Port 4173
#
# Requires: backend on $ApiBase with SIMULATION_ENABLED=true; Node 22+; Playwright
#   (apps/desktop dep). CORS must include the chosen origin (default candidates
#   http://127.0.0.1:8080 and :4173 — see apps/server/.env.example).

param(
    [string]$ApiBase = 'http://localhost:8000',
    [string]$User = 'dev',
    [string]$Pass = 'devpassword',
    [int]$Port = 8080,
    [switch]$Build,
    [switch]$SkipServe,
    [switch]$SkipJslibSmoke,
    [switch]$OpenBrowser,
    [int]$JslibTimeoutSec = 120,
    [string]$ProjectPath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg) { Write-Host ">> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "OK $msg" -ForegroundColor Green }
function Write-Err([string]$msg) { Write-Host $msg -ForegroundColor Red }
function Write-WarnStep([string]$msg) { Write-Host "!! $msg" -ForegroundColor Yellow }

function Test-PortListening([int]$p) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', $p, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(300)
        $connected = $ok -and $client.Connected
        $client.Close()
        return $connected
    } catch {
        return $false
    }
}

# True when :$Port already serves Unity WebGL index (not some other app on 8080).
function Test-WebGlHost([int]$p) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$p/" -UseBasicParsing -TimeoutSec 3
        $body = [string]$resp.Content
        return ($body -match 'createUnityInstance|UnityLoader|unity-canvas|unity-container|Build/.*\.loader\.js')
    } catch {
        return $false
    }
}

$logDir = Join-Path $ProjectPath 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$probeDir = Join-Path $logDir 'webgl-sse-probe'
New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
$sessionPath = Join-Path $probeDir 'session.json'

# Prefer -Port; if occupied by a non-WebGL app, fall back to other CORS-listed ports.
$requestedPort = $Port
$portCandidates = @($requestedPort, 8080, 4173) | Select-Object -Unique
$resolved = $null
foreach ($cand in $portCandidates) {
    if (-not (Test-PortListening $cand)) {
        $resolved = $cand
        break
    }
    if (Test-WebGlHost $cand) {
        $resolved = $cand
        break
    }
}
if ($null -eq $resolved) {
    Write-Err "No free CORS host port among: $($portCandidates -join ', '). Stop the occupant or pass -Port <free> (must be in CORS_ALLOW_ORIGINS)."
    exit 2
}
if ($resolved -ne $requestedPort) {
    Write-WarnStep "Port $requestedPort busy (non-WebGL) — using :$resolved (must be in CORS_ALLOW_ORIGINS)"
}
$Port = [int]$resolved

# --- Step A: CORS + SSE probe (Node, no Unity required) ---
Write-Step "A) Browser-origin SSE probe (Origin http://127.0.0.1:$Port)"

$probeJs = @'
const API = process.env.SPIKE_API || "http://localhost:8000";
const USER = process.env.SPIKE_USER || "dev";
const PASS = process.env.SPIKE_PASS || "devpassword";
const ORIGIN = process.env.SPIKE_ORIGIN || "http://127.0.0.1:8080";
const SESSION_OUT = process.env.SPIKE_SESSION_OUT || "";

function fail(m) { console.error("FAIL", m); process.exit(1); }

async function main() {
  const tokenRes = await fetch(`${API}/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: ORIGIN },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!tokenRes.ok) fail(`token ${tokenRes.status} ${await tokenRes.text()}`);
  const { access_token: token } = await tokenRes.json();
  if (!token) fail("no access_token");

  const createRes = await fetch(`${API}/v1/simulation/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Origin: ORIGIN,
    },
    body: JSON.stringify({ scenario: "town", seed: 42 }),
  });
  const acao = createRes.headers.get("access-control-allow-origin");
  console.log("create ACAO=", acao, "status=", createRes.status);
  if (!createRes.ok) fail(`create ${createRes.status} ${await createRes.text()}`);
  if (!acao || (acao !== ORIGIN && acao !== "*")) {
    fail(`CORS missing/wrong ACAO=${acao} (want ${ORIGIN}). Update CORS_ALLOW_ORIGINS and restart backend.`);
  }
  const run = await createRes.json();
  const runId = run.id;
  console.log("runId=", runId);

  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 15000);
  const sseRes = await fetch(`${API}/v1/simulation/runs/${encodeURIComponent(runId)}/stream`, {
    headers: {
      Accept: "text/event-stream",
      Authorization: `Bearer ${token}`,
      Origin: ORIGIN,
    },
    signal: ctrl.signal,
  });
  if (!sseRes.ok || !sseRes.body) fail(`SSE connect ${sseRes.status}`);
  const sseAcao = sseRes.headers.get("access-control-allow-origin");
  console.log("sse ACAO=", sseAcao, "status=", sseRes.status);

  const tickPromise = fetch(`${API}/v1/simulation/runs/${encodeURIComponent(runId)}/tick`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      Origin: ORIGIN,
    },
    body: "{}",
  }).then(async (r) => {
    console.log("tick status=", r.status);
    if (!r.ok) console.error("tick body", await r.text());
  }).catch((e) => console.error("tick err", e));

  const reader = sseRes.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  let sawEvent = false;
  let eventNames = [];
  try {
    while (!sawEvent) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() || "";
      for (const frame of parts) {
        const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        try {
          const ev = JSON.parse(dataLine.replace(/^data:\s?/, ""));
          const name = ev.type || ev.event || ev.name || JSON.stringify(ev).slice(0, 80);
          eventNames.push(name);
          console.log("SSE event:", name);
          if (String(name).includes("sim.") || String(name).includes("tick")) {
            sawEvent = true;
            break;
          }
          sawEvent = true;
          break;
        } catch {
          /* ignore */
        }
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") throw e;
  } finally {
    clearTimeout(t);
    try { ctrl.abort(); } catch { /* */ }
  }
  await tickPromise.catch(() => {});

  if (!sawEvent) fail("no SSE data frame within timeout");

  if (SESSION_OUT) {
    const fs = await import("node:fs");
    fs.writeFileSync(
      SESSION_OUT,
      JSON.stringify({ api: API, token, runId, origin: ORIGIN }, null, 2),
      "utf8",
    );
    console.log("session →", SESSION_OUT);
  }

  console.log("OK browser SSE path", eventNames.slice(0, 5).join(","));
  process.exit(0);
}

main().catch((e) => fail(String(e)));
'@

$probePath = Join-Path $probeDir 'probe.mjs'
Set-Content -Path $probePath -Value $probeJs -Encoding UTF8

$env:SPIKE_API = $ApiBase
$env:SPIKE_USER = $User
$env:SPIKE_PASS = $Pass
$env:SPIKE_ORIGIN = "http://127.0.0.1:$Port"
$env:SPIKE_SESSION_OUT = $sessionPath
node $probePath
if ($LASTEXITCODE -ne 0) {
    Write-Err 'Step A failed — fix CORS / SIMULATION_ENABLED / auth, then re-run.'
    exit $LASTEXITCODE
}
Write-Ok 'Step A: CORS + SSE browser path green'

if (-not (Test-Path $sessionPath)) {
    Write-Err "Step A did not write $sessionPath"
    exit 1
}
$session = Get-Content -Raw -Path $sessionPath | ConvertFrom-Json
$token = [string]$session.token
$runId = [string]$session.runId
if ([string]::IsNullOrEmpty($token) -or [string]::IsNullOrEmpty($runId)) {
    Write-Err 'session.json missing token/runId'
    exit 1
}

# --- Step B: WebGL build ---
$webglIndex = Join-Path $ProjectPath 'Builds\WebGL\index.html'
$webglDir = Join-Path $ProjectPath 'Builds\WebGL'
if ($Build) {
    Write-Step 'B) Building WebGL (-Build)'
    & (Join-Path $PSScriptRoot 'build-unity.ps1') -Target WebGL -ProjectPath $ProjectPath
    if (-not (Test-Path $webglIndex)) { throw "WebGL build missing after build-unity.ps1" }
    Write-Ok "B) WebGL → $webglIndex"
} elseif (Test-Path $webglIndex) {
    Write-Ok "B) WebGL build present: $webglIndex"
} else {
    Write-Host "B) WebGL build not present — run: pnpm town:build:webgl  (Step A already green)"
    Write-Ok 'Spike Step A passed (CORS+SSE). Build WebGL separately when ready for jslib smoke.'
    exit 0
}

# One-click URL (always print when we have a build + session)
$apiEnc = [uri]::EscapeDataString($ApiBase)
$tokenEnc = [uri]::EscapeDataString($token)
$runEnc = [uri]::EscapeDataString($runId)
$openUrl = "http://127.0.0.1:${Port}/?api=${apiEnc}&token=${tokenEnc}&run=${runEnc}"

Write-Host ''
Write-Host '=== One-click WebGL URL (jslib SSE) ===' -ForegroundColor Magenta
Write-Host $openUrl
Write-Host "Offline Demo (no backend): http://127.0.0.1:${Port}/?demo=1" -ForegroundColor DarkGray
Write-Host "Or: pnpm town:serve:webgl"
Write-Host "Manual: serve Builds/WebGL on :$Port, then open the URL above." -ForegroundColor DarkGray
Write-Host ''

if ($SkipServe) {
    Write-Ok 'SkipServe — URL printed; serve Builds/WebGL yourself to verify Unity jslib.'
    exit 0
}

# --- Step C: serve + optional Playwright jslib smoke ---
Write-Step "C) Serve WebGL on http://127.0.0.1:$Port"

$serveProc = $null
$startedServe = $false
try {
    $reuseOk = (Test-PortListening $Port) -and (Test-WebGlHost $Port)
    if ($reuseOk) {
        Write-Ok "Reusing existing Unity WebGL host on :$Port"
    }

    if (-not $reuseOk) {
        if (Test-PortListening $Port) {
            throw "Port $Port became busy before serve started — re-run the spike"
        }
        # Serve via the canonical Node server (sets Content-Encoding: gzip for Unity .gz
        # artifacts; plain `npx serve` omits it → "Unable to parse WebGL.framework.js.gz").
        $serveOut = Join-Path $probeDir 'serve.out.log'
        $serveErr = Join-Path $probeDir 'serve.err.log'
        $serveScript = Join-Path $PSScriptRoot 'serve-webgl.mjs'
        $serveProc = Start-Process -FilePath 'node' `
            -ArgumentList @($serveScript, '--root', $webglDir, '--port', "$Port", '--strict-port', '--no-open') `
            -WorkingDirectory $webglDir -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput $serveOut -RedirectStandardError $serveErr
        $startedServe = $true
        $ready = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 500
            if (Test-PortListening $Port) { $ready = $true; break }
            if ($serveProc.HasExited) { break }
        }
        if (-not $ready) {
            $tailOut = if (Test-Path $serveOut) { Get-Content $serveOut -Raw } else { '' }
            $tailErr = if (Test-Path $serveErr) { Get-Content $serveErr -Raw } else { '' }
            throw "Static server on :$Port did not become ready`n$tailOut`n$tailErr"
        }
        if (-not (Test-WebGlHost $Port)) {
            throw "Server on :$Port came up but index.html is not Unity WebGL — check Builds/WebGL"
        }
        Write-Ok "Static server pid=$($serveProc.Id) on :$Port"
    }

    if ($OpenBrowser) {
        Write-Step 'Opening browser (-OpenBrowser)'
        Start-Process $openUrl
    }

    if ($SkipJslibSmoke) {
        Write-Ok 'SkipJslibSmoke — static server left running for manual jslib check.'
        Write-Host "Open: $openUrl"
        if ($startedServe -and $null -ne $serveProc -and -not $serveProc.HasExited) {
            Write-Host "Stop later: Stop-Process -Id $($serveProc.Id) -Force   (or kill whatever listens on :$Port)"
            # Detach so finally does not tear down the host.
            $startedServe = $false
        }
        exit 0
    }

    Write-Step 'C2) Playwright jslib SSE smoke (fetch tee on Unity page)'
    $smokePath = Join-Path $PSScriptRoot 'webgl-jslib-smoke.mjs'
    if (-not (Test-Path $smokePath)) { throw "Missing $smokePath" }

    $desktopPw = Join-Path $ProjectPath '..\desktop\node_modules\playwright'
    if (Test-Path $desktopPw) {
        $env:SPIKE_PLAYWRIGHT = (Resolve-Path $desktopPw).Path
    }

    $env:SPIKE_URL = $openUrl
    $env:SPIKE_API = $ApiBase
    $env:SPIKE_TOKEN = $token
    $env:SPIKE_RUN_ID = $runId
    $env:SPIKE_TIMEOUT_MS = [string]($JslibTimeoutSec * 1000)

    node $smokePath
    $smokeCode = $LASTEXITCODE
    if ($smokeCode -ne 0) {
        Write-Err 'Step C2 jslib smoke failed (or timed out).'
        Write-Host ''
        Write-Host 'Manual fallback (one-click URL still valid while token lives):' -ForegroundColor Yellow
        Write-Host $openUrl
        Write-Host 'Expect HUD → SSE: connected, then live sim.tick_* / Advance Tick.'
        Write-Host 'If console shows ArgumentNullException/shader: rebuild WebGL after shader fallbacks,'
        Write-Host '  then re-run:  pnpm town:build:webgl && pnpm town:spike:webgl'
        Write-Host 'Or skip auto smoke:  powershell -File apps/town/scripts/spike-webgl-sse.ps1 -SkipJslibSmoke -OpenBrowser'
        if ($OpenBrowser) { Start-Process $openUrl }
        exit $smokeCode
    }
    Write-Ok 'Step C2: WebGL jslib SSE smoke green'
    Write-Ok '§15.2 spike: Step A (CORS+SSE) + Step C (jslib via Playwright) passed'
    exit 0
}
finally {
    if ($startedServe -and $null -ne $serveProc -and -not $serveProc.HasExited) {
        Write-Step "Stopping static server pid=$($serveProc.Id)"
        try { Stop-Process -Id $serveProc.Id -Force -ErrorAction SilentlyContinue } catch { }
        # npx may leave child node; best-effort kill by port
        try {
            Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
                ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
        } catch { }
    }
}
