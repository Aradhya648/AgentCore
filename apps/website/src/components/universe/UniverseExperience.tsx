"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { DOWNLOAD_PAGE_PATH, WEB_APP_URL } from "@/lib/download";
import { SECTIONS, SECTION_COUNT, progressStore } from "./timeline";

/**
 * 方案 C「3D 沉浸宇宙」的页面层：正常 DOM 滚动（不劫持），
 * 固定全屏 3D 画布做背景，章节文案覆盖其上；滚动进度写入
 * progressStore，由 3D 场景逐帧消费。
 *
 * 调试参数（截图自检用）：
 *   ?s=<0..6>  直接跳到第 N 章
 *   ?snap=1    相机与出场动画跳过阻尼（确定性构图）
 */

const Scene3D = dynamic(() => import("./Scene3D"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-muted-foreground">
      正在点亮星空…
    </div>
  ),
});

function BrandMark() {
  return (
    <svg width="24" height="24" viewBox="0 0 26 26" aria-hidden="true">
      <line x1="6" y1="7" x2="13" y2="13" stroke="var(--border)" strokeWidth="1.5" />
      <line x1="20" y1="7" x2="13" y2="13" stroke="var(--border)" strokeWidth="1.5" />
      <line x1="7" y1="20" x2="13" y2="13" stroke="var(--border)" strokeWidth="1.5" />
      <circle cx="13" cy="13" r="3.4" fill="var(--primary)" />
      <circle cx="6" cy="7" r="2.2" fill="var(--brand-2)" />
      <circle cx="20" cy="7" r="2.2" fill="var(--brand-2)" />
      <circle cx="7" cy="20" r="2.2" fill="var(--brand-2)" />
    </svg>
  );
}

function ScrollHint() {
  return (
    <div className="pointer-events-none mt-14 flex flex-col items-center gap-2 text-muted-foreground">
      <span className="text-xs tracking-[0.2em]">滚动开始旅程</span>
      <svg width="18" height="26" viewBox="0 0 18 26" aria-hidden="true">
        <rect
          x="1"
          y="1"
          width="16"
          height="24"
          rx="8"
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.5"
          strokeWidth="1.4"
        />
        <circle className="uv-scroll-dot" cx="9" cy="8" r="2.4" fill="var(--brand-2)" />
      </svg>
    </div>
  );
}

const RAIL_LABELS = ["序章", "孤独", "目标", "波次", "辩论", "可见", "终章"];

export default function UniverseExperience() {
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const reduceQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncReduced = () => {
      progressStore.reducedMotion = reduceQuery.matches;
    };
    syncReduced();
    reduceQuery.addEventListener("change", syncReduced);

    // 截图脚本/人工调试探针：window.__uvProgress 可直接读全局进度
    (window as unknown as Record<string, unknown>).__uvProgress = progressStore;

    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const max = Math.max(
          1,
          document.documentElement.scrollHeight - window.innerHeight,
        );
        const p = Math.min(1, Math.max(0, window.scrollY / max));
        progressStore.value = p;
        setActive(Math.round(p * (SECTION_COUNT - 1)));
      });
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    // 调试直达：?s=章节号 & ?snap=1
    const params = new URLSearchParams(window.location.search);
    if (params.get("snap") === "1") progressStore.snap = true;
    const s = Number(params.get("s"));
    if (Number.isFinite(s) && params.get("s") !== null) {
      const idx = Math.min(Math.max(0, Math.trunc(s)), SECTION_COUNT - 1);
      requestAnimationFrame(() => {
        const max =
          document.documentElement.scrollHeight - window.innerHeight;
        window.scrollTo({
          top: (idx / (SECTION_COUNT - 1)) * max,
          behavior: "instant",
        });
      });
    }
    onScroll();

    return () => {
      window.removeEventListener("scroll", onScroll);
      reduceQuery.removeEventListener("change", syncReduced);
      cancelAnimationFrame(raf);
    };
  }, []);

  const jumpTo = (i: number) => {
    const max = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({
      top: (i / (SECTION_COUNT - 1)) * max,
      behavior: progressStore.reducedMotion ? "instant" : "smooth",
    });
  };

  return (
    <div ref={rootRef} className="relative">
      {/* 固定 3D 舞台 */}
      <div className="fixed inset-0">
        <Scene3D />
        {/* 底部渐隐 + 四角暗角，提升文字可读性与「电影感」 */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(130% 100% at 50% 50%, transparent 58%, color-mix(in oklab, var(--background), transparent 35%) 100%)",
          }}
        />
      </div>

      {/* 顶部极简导航 */}
      <header className="fixed inset-x-0 top-0 z-40">
        <div className="container-x flex h-16 items-center justify-between">
          <a href="/" className="pointer-events-auto flex items-center gap-2.5">
            <BrandMark />
            <span className="text-[1.02rem] font-bold tracking-tight">AgentCore</span>
            <span className="rounded-md border border-border/70 px-2 py-0.5 text-xs text-muted-foreground">
              3D 概念预览
            </span>
          </a>
          <a
            href="/"
            className="btn btn-ghost pointer-events-auto px-3 py-1.5 text-sm"
          >
            返回官网
          </a>
        </div>
      </header>

      {/* 右侧章节轨道 */}
      <nav
        aria-label="章节导航"
        className="fixed right-5 top-1/2 z-40 hidden -translate-y-1/2 flex-col items-end gap-3 md:flex"
      >
        {SECTIONS.map((sec, i) => (
          <button
            key={sec.id}
            type="button"
            onClick={() => jumpTo(i)}
            className="group pointer-events-auto flex items-center gap-2"
            aria-label={`跳到章节：${RAIL_LABELS[i]}`}
          >
            <span
              className={`text-xs transition-opacity ${
                active === i
                  ? "opacity-90 text-brand-2"
                  : "opacity-0 text-muted-foreground group-hover:opacity-70"
              }`}
            >
              {RAIL_LABELS[i]}
            </span>
            <span
              className="h-2 w-2 rounded-full transition-all"
              style={{
                background:
                  active === i ? "var(--brand-2)" : "var(--border)",
                transform: active === i ? "scale(1.35)" : "scale(1)",
              }}
            />
          </button>
        ))}
      </nav>

      {/* 章节内容（每章正好一屏；容器不截获指针，面板才截获） */}
      <main className="pointer-events-none relative z-10">
        {SECTIONS.map((sec, i) => {
          const isHero = i === 0;
          const isFinale = i === SECTION_COUNT - 1;
          const alignCls =
            sec.align === "center"
              ? "items-center text-center"
              : sec.align === "right"
                ? "items-end text-left"
                : "items-start text-left";
          return (
            <section
              key={sec.id}
              id={sec.id}
              className={`container-x flex h-screen flex-col justify-center ${alignCls}`}
            >
              {isHero ? (
                <div className="pointer-events-auto flex max-w-3xl flex-col items-center">
                  <p className="eyebrow">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-2" />
                    {sec.eyebrow}
                  </p>
                  <h1 className="mt-6 text-5xl font-bold leading-[1.1] tracking-tight sm:text-6xl xl:text-7xl">
                    {sec.title}
                    <br />
                    <span className="text-gradient">{sec.titleAccent}</span>
                  </h1>
                  <p className="mt-6 text-lg text-muted-foreground">{sec.body}</p>
                  <ScrollHint />
                </div>
              ) : (
                <div
                  className={`uv-panel pointer-events-auto max-w-xl ${
                    isFinale ? "uv-panel-finale text-center" : ""
                  }`}
                >
                  <p className="eyebrow">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-2" />
                    {sec.eyebrow}
                  </p>
                  <h2
                    className={`mt-4 font-bold leading-snug tracking-tight ${
                      isFinale ? "text-4xl sm:text-5xl" : "text-3xl sm:text-4xl"
                    }`}
                  >
                    {sec.title}
                    {sec.titleAccent && (
                      <>
                        <br />
                        <span className="text-gradient">{sec.titleAccent}</span>
                      </>
                    )}
                  </h2>
                  <p className="mt-4 text-base leading-relaxed text-muted-foreground sm:text-lg">
                    {sec.body}
                  </p>
                  {isFinale && (
                    <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                      <a
                        href={WEB_APP_URL}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="btn btn-primary"
                      >
                        立即使用 · 网页版
                      </a>
                      <a href={DOWNLOAD_PAGE_PATH} className="btn btn-ghost">
                        下载客户端
                      </a>
                    </div>
                  )}
                </div>
              )}
            </section>
          );
        })}
      </main>
    </div>
  );
}
