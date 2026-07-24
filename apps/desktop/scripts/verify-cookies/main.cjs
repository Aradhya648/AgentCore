/**
 * Cookie round-trip verifier (方案 B 真机验证).
 *
 * This is a *standalone* Electron app whose only job is to answer one question:
 * does a credentialed fetch from the packaged renderer origin (`app://agentcore`)
 * to a real cross-site HTTPS API actually STORE the `Secure; SameSite=None` auth
 * cookies and RESEND them on the follow-up requests?
 *
 * It deliberately mirrors the production main process (apps/desktop/src/main/index.ts):
 * the SAME privileged scheme registration (standard + secure) and the SAME default
 * session. The renderer here is a 20-line page instead of the React bundle, but the
 * cookie behaviour under test (scheme origin + session jar + credentialed fetch) is
 * byte-identical to the real package — so a PASS here is a faithful PASS for the app.
 *
 * Drive it via verify.ps1 (which starts a prod-cookie backend + cloudflared tunnel
 * and passes VERIFY_API_URL). It prints a verdict and writes the full evidence JSON
 * to VERIFY_OUT (default: <tmp>/agentcore-cookie-verify.json), then exits 0 (PASS) /
 * 1 (FAIL) / 2 (harness/config error).
 */
"use strict";

const {
  app,
  BrowserWindow,
  protocol,
  net,
  session,
  ipcMain,
} = require("electron");
const { join, sep } = require("node:path");
const { pathToFileURL } = require("node:url");
const { writeFileSync } = require("node:fs");
const os = require("node:os");

const API_URL = (process.env.VERIFY_API_URL || "").replace(/\/+$/, "");
let API_HOST = null;
try {
  API_HOST = new URL(API_URL).hostname;
} catch {
  /* validated in whenReady */
}
const isLoopbackHost = (h) =>
  h === "127.0.0.1" || h === "localhost" || h === "::1";
// Force-trust a self-signed cert ONLY for a loopback API host (the local-HTTPS
// stand-in). A real remote domain must pass Chromium's normal CA verification so
// the remote run stays faithful — a genuine cert problem should fail it.
const TRUST_SELF_SIGNED = !!API_HOST && isLoopbackHost(API_HOST);
const USERNAME = process.env.VERIFY_USERNAME || "dev";
const PASSWORD = process.env.VERIFY_PASSWORD || "devpassword";
const OUT_PATH =
  process.env.VERIFY_OUT || join(os.tmpdir(), "agentcore-cookie-verify.json");
const TIMEOUT_MS = Number(process.env.VERIFY_TIMEOUT_MS || "45000");

// Production scheme privileges, copied verbatim from src/main/index.ts so the
// renderer origin is the real secure `app://agentcore` (not a file:// opaque one).
const APP_SCHEME = "app";
const APP_ORIGIN_HOST = "agentcore";
const RENDERER_ROOT = __dirname;

protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

// Accept the verifier's self-signed localhost cert (loopback API host only). For a
// real remote domain TRUST_SELF_SIGNED is false, so this never fires and Chromium's
// normal CA verification stands.
app.on("certificate-error", (event, _wc, url, _err, _cert, callback) => {
  try {
    if (TRUST_SELF_SIGNED && new URL(url).hostname === API_HOST) {
      event.preventDefault();
      callback(true);
      return;
    }
  } catch {
    /* fall through to default rejection */
  }
  callback(false);
});

function registerAppProtocol() {
  protocol.handle(APP_SCHEME, (request) => {
    const { pathname } = new URL(request.url);
    const relativePath =
      pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
    const filePath = join(RENDERER_ROOT, relativePath);
    if (!filePath.startsWith(RENDERER_ROOT + sep)) {
      return new Response("Forbidden", { status: 403 });
    }
    return net.fetch(pathToFileURL(filePath).toString());
  });
}

/** Map an Electron cookie to the fields we care about for the verdict. */
function pickCookie(c) {
  if (!c) return null;
  return {
    name: c.name,
    domain: c.domain,
    path: c.path,
    secure: c.secure,
    httpOnly: c.httpOnly,
    sameSite: c.sameSite, // Electron reports SameSite=None as "no_restriction"
    session: c.session,
  };
}

function finish(result) {
  // SameSite=None surfaces as "no_restriction" in Electron's cookie API.
  const isNone = (c) => c && c.sameSite === "no_restriction";
  const jar = result.cookiesAfterLogin || [];
  const access = jar.find((c) => c.name === "access_token") || null;
  const refresh = jar.find((c) => c.name === "refresh_token") || null;

  const checks = {
    "login 200": result.steps?.login?.status === 200,
    "access_token cookie stored": !!access,
    "access_token Secure": access?.secure === true,
    "access_token SameSite=None": isNone(access),
    "refresh_token cookie stored": !!refresh,
    "refresh_token Secure": refresh?.secure === true,
    "refresh_token SameSite=None": isNone(refresh),
    "refresh 200 (refresh cookie resent)":
      result.steps?.refresh?.status === 200,
    "authed /me 200 (access cookie resent)": result.steps?.me?.status === 200,
  };

  const failed = Object.entries(checks)
    .filter(([, ok]) => !ok)
    .map(([k]) => k);
  const pass = failed.length === 0 && !result.error;

  const verdict = {
    pass,
    apiUrl: API_URL,
    error: result.error || null,
    checks,
    failed,
    steps: result.steps || null,
    me: result.me || null,
    cookies: { access, refresh, all: jar },
    at: new Date().toISOString(),
  };

  try {
    writeFileSync(OUT_PATH, JSON.stringify(verdict, null, 2), "utf-8");
  } catch (e) {
    process.stderr.write(`[verify] could not write ${OUT_PATH}: ${e}\n`);
  }

  const line = (s) => process.stdout.write(`${s}\n`);
  line("");
  line("==================== COOKIE VERIFY ====================");
  line(`API: ${API_URL}`);
  if (result.error) line(`ERROR: ${result.error}`);
  for (const [name, ok] of Object.entries(checks)) {
    line(`  [${ok ? "PASS" : "FAIL"}] ${name}`);
  }
  line(`evidence: ${OUT_PATH}`);
  line(`COOKIE VERIFY: ${pass ? "PASS" : "FAIL"}`);
  line("=======================================================");

  app.exit(result.error ? 2 : pass ? 0 : 1);
}

let done = false;
const guard = setTimeout(() => {
  if (done) return;
  done = true;
  finish({ error: `timed out after ${TIMEOUT_MS}ms` });
}, TIMEOUT_MS);

ipcMain.handle("verify:config", () => ({
  apiUrl: API_URL,
  username: USERNAME,
  password: PASSWORD,
}));

// Snapshot every cookie the default session would hand back, mapped down to the
// fields the verdict asserts on. Called by the renderer right after login.
ipcMain.handle("verify:cookies", async () => {
  const all = await session.defaultSession.cookies.get({});
  const apiHost = new URL(API_URL).hostname;
  return all
    .filter((c) => {
      const d = (c.domain || "").replace(/^\./, "");
      return d === apiHost;
    })
    .map(pickCookie);
});

ipcMain.handle("verify:report", (_e, result) => {
  if (done) return;
  done = true;
  clearTimeout(guard);
  finish(result || {});
});

app.whenReady().then(async () => {
  if (!API_URL) {
    finish({ error: "VERIFY_API_URL is required (the HTTPS API URL)" });
    return;
  }
  registerAppProtocol();
  // Same loopback-only self-signed trust as the certificate-error handler, on the
  // fetch path. Real domains → -3 (use Chromium's real CA verification).
  session.defaultSession.setCertificateVerifyProc((request, callback) => {
    callback(TRUST_SELF_SIGNED && request.hostname === API_HOST ? 0 : -3);
  });
  const win = new BrowserWindow({
    show: false,
    webPreferences: {
      preload: join(__dirname, "preload.cjs"),
      sandbox: false,
    },
  });
  try {
    await win.loadURL(`${APP_SCHEME}://${APP_ORIGIN_HOST}/index.html`);
  } catch (e) {
    finish({ error: `failed to load app://agentcore renderer: ${e}` });
  }
});
