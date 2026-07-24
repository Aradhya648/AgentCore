<#
  方案 B 一键真机验证（本地自签 HTTPS 版）。

  目标不变：客观判定打包态渲染进程 origin `app://agentcore` 跨站访问 HTTPS API 时，
  `Secure; SameSite=None` 鉴权 cookie 是否真的落盘并回传（登录→刷新→/me）。

  传输选型：原计划用 cloudflared 临时隧道拿公网 HTTPS，但本机网络到 Cloudflare 公网
  边缘不可达（隧道注册成功、公网 URL 连不上）。改用**本地自签 HTTPS**：uvicorn 直接以
  TLS 起在 https://127.0.0.1:PORT。它对 `app://agentcore` 同样是「跨站 + HTTPS + Secure」，
  完整复现生产 cookie 条件，且离线确定、与外网无关（cookie 语义只看 scheme/site/Secure/
  SameSite，与服务器物理位置无关）。Electron 仅对该 API 主机放行自签证书。

  步骤：
    1. 生成自签证书（cryptography）到 <root>/.tools/tls
    2. 幂等播种测试账号（dev / devpassword）
    3. 以生产 cookie 姿态（DEBUG=false, COOKIE_SECURE=true, COOKIE_SAMESITE=none）
       用 uvicorn TLS 在 https://127.0.0.1:PORT 起后端（复用 .env 的 DATABASE_URL）
    4. 跑 main.cjs（Electron）：在 app://agentcore 下登录→查 cookie→刷新→/me
    5. 无论成败拆掉后端；打印证据 JSON 与判定

  用法（从仓库任意位置）：
    pwsh -File apps/desktop/scripts/verify-cookies/verify.ps1
  退出码：0=PASS，1=FAIL，2=编排/环境错误。
#>
[CmdletBinding()]
param(
  # REMOTE 模式：传入已部署 API 的 base URL（如 https://app.fashitianxia.xyz/api）后，
  # 直接打真实环境（真网络 / 真 CA / 真 Nginx 反代），不起本地后端、不造自签证书。
  # 需要该环境数据库里的真实账号（-Username / -Password）。留空 = 本地自签 HTTPS 模式。
  [string]$ApiUrl = "",
  [int]$Port = 8443,
  [string]$Username = "dev",
  [string]$Password = "devpassword"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$serverDir = Join-Path $root "apps\server"
$desktopDir = Join-Path $root "apps\desktop"
$toolsDir = Join-Path $root ".tools"
$tlsDir = Join-Path $toolsDir "tls"
$logDir = Join-Path $toolsDir "verify-logs"
New-Item -ItemType Directory -Force -Path $toolsDir, $tlsDir, $logDir | Out-Null

$beOut = Join-Path $logDir "backend.out.log"
$beErr = Join-Path $logDir "backend.err.log"
$outJson = Join-Path $toolsDir "cookie-verify.json"
$cert = Join-Path $tlsDir "cert.pem"
$key = Join-Path $tlsDir "key.pem"
$apiUrl = "https://127.0.0.1:$Port"

$backend = $null

# Health gate uses curl.exe -k: WinPS 5.1's Invoke-WebRequest can't reliably accept a
# self-signed cert (its .NET cert callback is flaky), whereas curl -k handles it
# cleanly. The real HTTPS-from-app:// test is Electron's job (it trusts the cert via
# setCertificateVerifyProc); this is just a "backend is serving" gate.
function Wait-ForUrl([string]$url, [int]$timeoutSec) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $code = & curl.exe -k -s -o NUL -w "%{http_code}" --max-time 5 $url 2>$null
    if ($code -match '^(2|3|4)\d\d$') { return $true }
    Start-Sleep -Milliseconds 700
  }
  return $false
}

try {
  if ($ApiUrl) {
    # REMOTE：直打真实已部署 API（真网络 / 真 CA / 真 Nginx）。不起本地后端、不造证书。
    $apiUrl = $ApiUrl.TrimEnd('/')
    Write-Host "[verify] REMOTE mode against $apiUrl (no local backend/cert)"
    if (-not (Wait-ForUrl "$apiUrl/livez" 20)) {
      Write-Host "[verify] remote API not reachable at $apiUrl/livez" -ForegroundColor Red
      exit 2
    }
    Write-Host "[verify] remote API reachable."
  }
  else {
    # 1) 自签证书
    Write-Host "[verify] generating self-signed cert..."
    Push-Location $serverDir
    try { & uv run python (Join-Path $desktopDir "scripts\verify-cookies\gen_cert.py") $tlsDir }
    finally { Pop-Location }
    if (-not (Test-Path $cert) -or -not (Test-Path $key)) {
      Write-Host "[verify] cert generation failed" -ForegroundColor Red
      exit 2
    }

    # 2) 播种测试账号（幂等）
    Write-Host "[verify] seeding test user '$Username'..."
    $env:DEV_USERNAME = $Username
    $env:DEV_PASSWORD = $Password
    Push-Location $serverDir
    try { & uv run python scripts/seed_dev_user.py } finally { Pop-Location }

    # 3) prod-cookie 后端（uvicorn TLS；throwaway 密钥让 fail-closed 校验通过）
    $jwt = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    $enc = -join ((1..64) | ForEach-Object { '{0:x}' -f (Get-Random -Maximum 16) })
    $env:DEBUG = "false"
    $env:COOKIE_SECURE = "true"
    $env:COOKIE_SAMESITE = "none"
    $env:CORS_ALLOW_ORIGINS = "app://agentcore"
    $env:JWT_SECRET_KEY = $jwt
    $env:ENCRYPTION_KEY = $enc
    Write-Host "[verify] starting prod-cookie TLS backend on $apiUrl (DEBUG=false, SameSite=None, Secure)..."
    $backend = Start-Process -FilePath "uv" -ArgumentList @(
      "run", "python", "-m", "uvicorn", "agentcore.main:app",
      "--host", "127.0.0.1", "--port", "$Port",
      "--ssl-keyfile", $key, "--ssl-certfile", $cert
    ) -WorkingDirectory $serverDir -NoNewWindow -PassThru `
      -RedirectStandardOutput $beOut -RedirectStandardError $beErr

    if (-not (Wait-ForUrl "$apiUrl/livez" 60)) {
      Write-Host "[verify] backend did not become healthy. Last stderr:" -ForegroundColor Red
      if (Test-Path $beErr) { Get-Content $beErr -Tail 40 }
      exit 2
    }
    Write-Host "[verify] backend healthy at $apiUrl"
  }

  # 4) Electron 校验（app://agentcore 真实 origin）
  Write-Host "[verify] running Electron cookie round-trip..."
  $env:VERIFY_API_URL = $apiUrl
  $env:VERIFY_USERNAME = $Username
  $env:VERIFY_PASSWORD = $Password
  $env:VERIFY_OUT = $outJson
  Push-Location $desktopDir
  try {
    & pnpm exec electron scripts/verify-cookies
    $code = $LASTEXITCODE
  } finally { Pop-Location }

  Write-Host ""
  if (Test-Path $outJson) {
    Write-Host "[verify] evidence ($outJson):"
    Get-Content $outJson -Raw | Write-Host
  }
  Write-Host "[verify] electron exit code: $code"
  exit $code
}
finally {
  if ($backend) {
    # Kill the whole tree: Start-Process captured the `uv` wrapper, but the actual
    # uvicorn server runs as a python CHILD — Stop-Process on the parent alone
    # orphans it (leaves :PORT held, breaking the next run). taskkill /T tears down
    # the wrapper + its children so re-runs always bind a fresh backend.
    try { & taskkill /PID $backend.Id /T /F 2>$null | Out-Null } catch {}
  }
}
