import AgentMapVerticalSimple from "@/components/agentmap/AgentMapVerticalSimple";
import AgentWarMapPortrait from "@/components/agentmap/AgentWarMapPortrait";

/**
 * 内部预览页：并排比较两版「竖向协作图」在 Hero 右栏中的落位（左文右图情境）。
 * - 方案A：简化竖图（2 秒看懂的主干叙事，去机制噪音）
 * - 方案B：完整竖图（保留 8 队员 + 工具/记忆/升级/A2A 全机制，连线已做去蛛网手术）
 * 仅用于决策选型，定稿后删除本路由。访问 /preview/maps
 */
export const metadata = {
  title: "协作图选型预览",
  robots: { index: false, follow: false },
};

function HeroCopy() {
  return (
    <div className="max-w-xl">
      <p className="eyebrow">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
        协作智能平台
      </p>
      <h3 className="mt-5 text-4xl font-bold leading-[1.1] tracking-tight sm:text-5xl">
        <span className="text-gradient">协作，</span>
        <br />
        是更高级的智能
      </h3>
      <p className="mt-6 text-lg leading-relaxed text-muted-foreground">
        一句需求，CEO 主 Agent 自动组建团队，按依赖关系分波次推进——
        串行、并行、辩论、互审，全程可见。
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <span className="btn btn-primary">下载客户端</span>
        <span className="btn btn-ghost">看团队如何协作</span>
      </div>
    </div>
  );
}

function WaveLegend() {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/60 pt-3 text-xs text-muted-foreground">
      <span className="inline-flex shrink-0 items-center gap-1.5">
        <svg width="22" height="8" viewBox="0 0 22 8" aria-hidden="true">
          <line x1="1" y1="4" x2="15" y2="4" stroke="var(--primary)" strokeOpacity={0.7} strokeWidth={1.6} />
          <polygon points="15,1 21,4 15,7" fill="var(--primary)" fillOpacity={0.7} />
        </svg>
        任务流向
      </span>
      <span className="inline-flex shrink-0 items-center gap-1.5">
        <svg width="22" height="8" viewBox="0 0 22 8" aria-hidden="true">
          <line x1="4" y1="4" x2="18" y2="4" stroke="var(--brand-2)" strokeOpacity={0.6} strokeWidth={1.6} strokeDasharray="4 3" />
        </svg>
        协作通信
      </span>
      <span className="min-w-0">波次 ①并行 ②依赖 ③辩论</span>
    </div>
  );
}

export default function MapsPreviewPage() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="container-x py-12">
        <p className="eyebrow">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
          内部选型预览 · 定稿后删除
        </p>
        <h1 className="mt-4 text-3xl font-bold tracking-tight sm:text-4xl">
          Hero 协作图 · 两版竖图对比
        </h1>
        <p className="mt-3 max-w-3xl text-muted-foreground">
          同一份「新产品上市调研」协作，两种密度的竖向图，均放在 Hero「左文右图」情境里。
          A 主打一眼看懂；B 保留完整机制但已做去蛛网手术。
        </p>
      </div>

      {/* ── 方案A 简化竖图 ── */}
      <section className="border-t border-border/60 bg-[color-mix(in_oklab,var(--primary),transparent_97%)]">
        <div className="container-x py-12">
          <div className="mb-6 flex items-baseline gap-3">
            <span className="rounded-full bg-primary px-3 py-1 text-sm font-bold text-primary-foreground">
              方案A
            </span>
            <h2 className="text-xl font-semibold">简化竖图 · 主干叙事（2 秒看懂）</h2>
          </div>
          <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
            <HeroCopy />
            <div className="w-full lg:justify-self-end">
              <div className="surface mx-auto w-full max-w-[440px] p-5 backdrop-blur-md sm:p-6">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="eyebrow">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                    一次协作 · 概览
                  </p>
                  <span className="shrink-0 text-sm text-muted-foreground">
                    6 队员 · 3 波次
                  </span>
                </div>
                <AgentMapVerticalSimple />
                <WaveLegend />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 方案B 完整竖图 ── */}
      <section className="border-t border-border/60">
        <div className="container-x py-12">
          <div className="mb-6 flex items-baseline gap-3">
            <span className="rounded-full bg-primary px-3 py-1 text-sm font-bold text-primary-foreground">
              方案B
            </span>
            <h2 className="text-xl font-semibold">
              完整竖图 · 全机制作战图（只留竖图）
            </h2>
          </div>
          <div className="grid items-center gap-12 lg:grid-cols-[0.82fr_1.18fr]">
            <HeroCopy />
            <div className="w-full lg:justify-self-end">
              <div className="surface mx-auto w-full max-w-[600px] p-5 backdrop-blur-md sm:p-6">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="eyebrow">
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
                    一次协作 · 实时作战图
                  </p>
                  <span className="shrink-0 text-sm text-muted-foreground">
                    8 队员 · 3 波次
                  </span>
                </div>
                <AgentWarMapPortrait />
                <WaveLegend />
              </div>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
