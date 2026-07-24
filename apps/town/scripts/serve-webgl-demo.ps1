# Serve AgentTown WebGL build and open the Offline Demo (?demo=1) — no backend / LLM required.
#
#   pnpm town:serve:webgl                  # -> node apps/town/scripts/serve-webgl.mjs
#   powershell -File apps/town/scripts/serve-webgl-demo.ps1
#   powershell -File apps/town/scripts/serve-webgl-demo.ps1 -Port 4173 -Pack festival -NoBrowser
#
# Thin wrapper around serve-webgl.mjs (the canonical server). The Node server sets
# Content-Encoding: gzip for Unity's pre-compressed .gz artifacts — plain `npx serve`
# does not, which makes Unity fail with "Unable to parse Build/WebGL.framework.js.gz!".

[CmdletBinding()]
param(
    [int]$Port = 8080,
    [string]$Pack = 'price_surge',
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$serve = Join-Path $scriptDir 'serve-webgl.mjs'
if (-not (Test-Path $serve)) { throw "Missing $serve" }

$nodeArgs = @($serve, '--port', "$Port")
if (-not [string]::IsNullOrWhiteSpace($Pack)) { $nodeArgs += @('--pack', $Pack) }
if ($NoBrowser) { $nodeArgs += '--no-open' }

node @nodeArgs
exit $LASTEXITCODE
