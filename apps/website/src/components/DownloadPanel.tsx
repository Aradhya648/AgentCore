"use client";

import {
  MOBILE_WEB_URL,
  RELEASES_LATEST,
  SYSTEM_REQUIREMENTS,
  platformsFromArtifacts,
  type PlatformId,
} from "@/lib/download";
import { useDesktopRelease } from "@/hooks/useDesktopRelease";
import { useEffect, useMemo, useState } from "react";

function detectPlatform(): PlatformId {
  if (typeof navigator === "undefined") return "win";
  const ua = navigator.userAgent.toLowerCase();
  // Android UA also contains "linux" — check android first.
  if (ua.includes("android")) return "android";
  if (ua.includes("mac")) return "mac";
  if (ua.includes("linux")) return "linux";
  return "win";
}

function DownloadIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 1.8v8.2m0 0L4.6 6.6M8 10 11.4 6.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M2.6 10.8v2.2a1 1 0 0 0 1 1h8.8a1 1 0 0 0 1-1v-2.2"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function DownloadPanel() {
  const [platform, setPlatform] = useState<PlatformId>("win");
  const { artifacts } = useDesktopRelease();

  const platforms = useMemo(
    () => platformsFromArtifacts(artifacts),
    [artifacts],
  );

  useEffect(() => {
    setPlatform(detectPlatform());
  }, []);

  const primary = platforms.find((p) => p.id === platform) ?? platforms[0];
  const primaryReady = primary.available && primary.url;
  const primaryVersion =
    primary.id === "android"
      ? artifacts.androidVersion || artifacts.version
      : artifacts.version;

  return (
    <div className="grid gap-8 lg:grid-cols-[1.2fr_1fr]">
      {/* 主 CTA：OS 感知 */}
      <div className="surface p-8 sm:p-10">
        <p className="eyebrow">推荐下载</p>
        <h2 className="mt-3 text-2xl font-bold sm:text-3xl">
          {primary.label}
          <span className="ml-2 text-base font-normal text-muted-foreground">
            v{primaryVersion}
          </span>
        </h2>
        <p className="mt-2 text-muted-foreground">{primary.subtitle}</p>

        {primaryReady ? (
          <>
            <a
              href={primary.url}
              className="btn btn-primary mt-8 w-full justify-center py-3.5 text-base sm:w-auto sm:px-10"
            >
              <DownloadIcon />
              下载 {primary.label} 版
            </a>
            {primary.fileLabel ? (
              <p className="mt-4 text-sm text-muted-foreground">
                {primary.fileLabel}
              </p>
            ) : null}
          </>
        ) : (
          <div className="mt-8 rounded-xl border border-border/80 bg-accent/30 px-5 py-4 text-sm text-muted-foreground">
            {primary.id === "mac"
              ? "macOS 版尚未随本次构建发布。请先使用 Windows 版，或稍后再试。"
              : primary.id === "android"
                ? "Android APK 尚未发布。请先下载桌面版，或关注后续更新。"
                : `${primary.label} 版尚未发布。请先下载已提供的平台安装包，或关注后续更新。`}
          </div>
        )}

        <p className="mt-6 text-sm leading-relaxed text-muted-foreground">
          {primary.id === "android"
            ? "APK 为侧载安装包，安装时需允许未知来源。"
            : "已安装用户无需重复下载——应用会在后台检查更新并在就绪后提示重启安装。"}
        </p>
      </div>

      {/* 全平台列表 + 其他入口 */}
      <div className="space-y-4">
        <p className="text-sm font-semibold">所有平台</p>
        {platforms.map((p) => (
          <div
            key={p.id}
            className="surface flex items-center justify-between gap-4 p-4"
          >
            <div>
              <p className="font-semibold">{p.label}</p>
              <p className="text-sm text-muted-foreground">{p.subtitle}</p>
            </div>
            {p.available && p.url ? (
              <a
                href={p.url}
                className="btn btn-ghost shrink-0 px-3 py-1.5 text-sm"
              >
                下载
              </a>
            ) : (
              <span className="shrink-0 rounded-md border border-border px-2.5 py-1 text-xs text-muted-foreground">
                即将推出
              </span>
            )}
          </div>
        ))}

        <div className="surface p-4 text-sm">
          <p className="font-semibold">其他入口</p>
          <ul className="mt-3 space-y-2 text-muted-foreground">
            <li>
              <a
                href={MOBILE_WEB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                手机网页版（浏览器打开，无需安装）
              </a>
            </li>
            <li>
              <a
                href={artifacts.releaseNotesUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                查看 v{artifacts.version} 发布说明
              </a>
            </li>
            <li>
              <a
                href={RELEASES_LATEST}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                所有历史版本（GitHub Releases）
              </a>
            </li>
          </ul>
        </div>
      </div>

      {/* 系统要求 */}
      <div className="surface p-6 lg:col-span-2">
        <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
          <div>
            <p className="font-semibold">系统要求 · Windows</p>
            <ul className="mt-4 grid gap-2">
              {SYSTEM_REQUIREMENTS.win.map((item) => (
                <li
                  key={item}
                  className="flex items-start gap-2 text-sm text-muted-foreground"
                >
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-2" />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          {platforms.find((p) => p.id === "mac")?.available ? (
            <div>
              <p className="font-semibold">系统要求 · macOS</p>
              <ul className="mt-4 grid gap-2">
                {SYSTEM_REQUIREMENTS.mac.map((item) => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-sm text-muted-foreground"
                  >
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-2" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {platforms.find((p) => p.id === "android")?.available ? (
            <div>
              <p className="font-semibold">系统要求 · Android</p>
              <ul className="mt-4 grid gap-2">
                {SYSTEM_REQUIREMENTS.android.map((item) => (
                  <li
                    key={item}
                    className="flex items-start gap-2 text-sm text-muted-foreground"
                  >
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-brand-2" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
