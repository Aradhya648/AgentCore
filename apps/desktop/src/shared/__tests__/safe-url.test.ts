// XSS-002 (前端XSS·外链交付) regression + red-team PoC: the `isSafeExternalUrl` allow-list
// is the only thing standing between an attacker-influenceable `target="_blank"` URL and
// the Electron `shell.openExternal` OS-handoff. This battery pins that every dangerous /
// local-execution scheme is rejected and only true web-navigable links pass, so a refactor
// can't quietly re-open the door (a click-to-launch `ms-msdt:` / `file://` vector on Windows).

import { isSafeExternalUrl } from "@shared/safe-url";
import { describe, expect, it } from "vitest";

describe("isSafeExternalUrl — allows real web-navigable links", () => {
  it.each([
    "http://example.com",
    "http://example.com/path?q=1#frag",
    "https://example.com",
    "https://sub.example.com/a/b?c=d",
    "HTTPS://EXAMPLE.COM", // scheme is case-insensitive
    "mailto:user@example.com",
    "mailto:user@example.com?subject=hi",
  ])("allows %s", (url) => {
    expect(isSafeExternalUrl(url)).toBe(true);
  });
});

describe("isSafeExternalUrl — blocks dangerous / non-web schemes (the attack payloads)", () => {
  it.each([
    "file:///etc/passwd",
    "file://C:/Windows/System32/cmd.exe",
    "ms-msdt:/id PCWDiagnostic", // Follina-class Windows protocol handler
    "search-ms:query=x",
    "ms-officecmd:{}",
    "javascript:alert(document.cookie)",
    "JaVaScRiPt:alert(1)", // case-evasion
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "custom-app://launch/payload",
    "chrome://settings",
    "ftp://example.com/file", // not on the allow-list either
    "tel:+123456789", // intentionally not allowed (only http/https/mailto)
  ])("blocks %s", (url) => {
    expect(isSafeExternalUrl(url)).toBe(false);
  });
});

describe("isSafeExternalUrl — blocks malformed / relative / non-string input", () => {
  it.each([
    "",
    "   ",
    "not a url",
    "//evil.com", // protocol-relative (no scheme) → never handed to the OS shell
    "/relative/path",
    "#hash",
    "example.com", // bare host, no scheme
  ])("blocks %p", (url) => {
    expect(isSafeExternalUrl(url)).toBe(false);
  });

  it("blocks non-string input", () => {
    expect(isSafeExternalUrl(undefined)).toBe(false);
    expect(isSafeExternalUrl(null)).toBe(false);
    expect(isSafeExternalUrl(42)).toBe(false);
    expect(isSafeExternalUrl({})).toBe(false);
  });
});
