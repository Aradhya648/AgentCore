"use client";

import { DESKTOP_VERSION } from "@/lib/download";
import { useDesktopRelease } from "@/hooks/useDesktopRelease";

export default function DownloadPageHero() {
  const { artifacts } = useDesktopRelease();
  const version = artifacts.version || DESKTOP_VERSION;

  return (
    <div className="mx-auto max-w-4xl text-center">
      <p className="eyebrow">Desktop · v{version}</p>
      <h1 className="mt-4 text-4xl font-bold tracking-tight sm:text-5xl">
        下载 AgentCore 桌面客户端
      </h1>
      <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-muted-foreground">
        Windows 与 macOS（Apple Silicon）Multi-Agent 协作工作台。
      </p>
    </div>
  );
}
