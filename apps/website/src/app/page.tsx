import CollaborationNetwork from "@/components/CollaborationNetwork";
import HeroFlow from "@/components/HeroFlow";
import Reveal from "@/components/Reveal";
import { DOWNLOAD_PAGE_PATH, MOBILE_WEB_URL, WEB_APP_URL } from "@/lib/download";

const NAV = [
  { href: "#value", label: "能力" },
  { href: "#how", label: "如何协作" },
  { href: "#compare", label: "对比" },
  { href: "#ecosystem", label: "生态" },
];

const VALUES = [
  {
    title: "多 Agent 协作",
    body: "一句需求，CEO 主 Agent 自动组建团队，按依赖关系分波次推进——串行、并行、辩论、互审，统一编排。不是一个助手分饰多角，而是一支真正分工的团队。",
  },
  {
    title: "全程可见",
    body: "谁在做什么、为什么这样决策、调用了哪些工具、花了多少成本，全部实时可见。协作不再是黑箱，而是一张你看得懂的团队作战图。",
  },
  {
    title: "你是领导者",
    body: "你不再绞尽脑汁写提示词去「使唤」一个工具。你像管理团队一样下达目标、审阅产出、随时介入，做最终决策。",
  },
];

const CAPABILITIES = [
  "多轮对话",
  "多 Agent 执行",
  "动态角色分配",
  "工具调用",
  "进度可视化",
  "跨会话记忆",
];

const STEPS = [
  {
    no: "01",
    title: "你下达目标",
    body: "用自然语言说出你要什么，像对团队负责人交代任务，无需拆解步骤。",
  },
  {
    no: "02",
    title: "CEO 组建团队",
    body: "CEO 主 Agent 理解任务，按需委派子任务、动态分配角色与工具，定下依赖关系（DAG）。",
  },
  {
    no: "03",
    title: "团队分波推进",
    body: "调度器按依赖波次编排，多个 Agent 并行执行、共享工作区、彼此协商与互审。",
  },
  {
    no: "04",
    title: "你审阅决策",
    body: "全过程实时可见，你随时介入、采纳或调整，对最终产出拍板。",
  },
];

const ROLES = [
  { product: "ChatGPT / Claude", was: "提示者 · Prompter" },
  { product: "Cursor / Codex", was: "指令者 · Commander" },
  { product: "AgentCore", was: "领导者 · Leader", highlight: true },
];

const COMPARE = [
  {
    dim: "怎么干活",
    others: "一个助手把所有事串着做，前后全靠它一个人",
    ours: "一支团队各干各的，能同时推进、按依赖关系交接",
  },
  {
    dim: "有人把关吗",
    others: "自己出结果，没人复查，结论未经论证",
    ours: "Agent 之间互审辩论，有「质检」环节",
  },
  {
    dim: "你看得见吗",
    others: "只见最终结果，中间决策是黑箱",
    ours: "谁在做什么、为什么这样决策，实时可见",
  },
  {
    dim: "能扩展吗",
    others: "配一个 Agent 的提示词和工具",
    ours: "工具 / 技能 / 规则 / Agent / 团队，五类资产可沉淀复用",
  },
];

const ECOSYSTEM = [
  { name: "工具 Tool", desc: "接入你的数据库、API、文件系统" },
  { name: "技能 Skill", desc: "沉淀你的分析流程、写作规范" },
  { name: "规则 Rule", desc: "团队行为的红线与偏好" },
  { name: "Agent", desc: "配好角色的专精队员" },
  { name: "团队 Team", desc: "一键复用整支团队配置" },
];

function BrandMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
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

function Dot() {
  return <span className="inline-block h-1.5 w-1.5 rounded-full bg-brand-2" />;
}

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
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

function WebIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle
        cx="8"
        cy="8"
        r="6.3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <path
        d="M1.7 8h12.6M8 1.7c1.9 1.7 2.9 3.9 2.9 6.3S9.9 12.6 8 14.3C6.1 12.6 5.1 10.4 5.1 8S6.1 3.4 8 1.7Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function Home() {
  return (
    <div className="relative">
      {/* ── 顶部导航 ── */}
      <header className="sticky top-0 z-50 border-b border-border/60 bg-[color-mix(in_oklab,var(--background),transparent_25%)] backdrop-blur-xl">
        <nav className="container-x flex h-16 items-center justify-between">
          <a href="#top" className="flex items-center gap-2.5">
            <BrandMark />
            <span className="text-[1.05rem] font-bold tracking-tight">AgentCore</span>
            <span className="hidden rounded-md border border-border px-2 py-0.5 text-xs text-muted-foreground sm:inline">
              协作智能平台
            </span>
          </a>
          <ul className="hidden items-center gap-7 text-sm text-muted-foreground md:flex">
            {NAV.map((item) => (
              <li key={item.href}>
                <a
                  href={item.href}
                  className="transition-colors hover:text-foreground"
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
          <div className="flex items-center gap-2 sm:gap-3">
            <a
              href={MOBILE_WEB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-ghost hidden px-3 py-2 text-sm sm:inline-flex"
            >
              手机网页版
            </a>
            <a
              href={DOWNLOAD_PAGE_PATH}
              className="btn btn-ghost hidden px-3 py-2 text-sm sm:inline-flex"
            >
              <DownloadIcon />
              下载客户端
            </a>
            <a
              href={WEB_APP_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-primary px-4 py-2 text-sm"
            >
              <WebIcon />
              网页版
            </a>
          </div>
        </nav>
      </header>

      <main id="top">
        {/* ── Hero ── */}
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 -z-10">
            <CollaborationNetwork />
          </div>
          {/* 文字侧可读性蒙版：左侧压暗保证文案清晰，右侧让协作网络透出。 */}
          <div
            aria-hidden="true"
            className="absolute inset-0 -z-10"
            style={{
              background:
                "linear-gradient(90deg, color-mix(in oklab, var(--background), transparent 6%) 0%, color-mix(in oklab, var(--background), transparent 42%) 46%, transparent 78%)",
            }}
          />
          <div className="container-x grid min-h-[88vh] items-center gap-12 py-24 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="float-in max-w-2xl">
              <p className="eyebrow">
                <Dot />
                协作智能平台 · Collaborative Intelligence Platform
              </p>
              <h1 className="mt-6 text-5xl font-bold leading-[1.08] tracking-tight sm:text-6xl xl:text-7xl">
                <span className="text-gradient">协作，</span>
                <br />
                是更高级的智能
              </h1>
              <figure className="relative mt-8 max-w-2xl overflow-hidden rounded-xl bg-[color-mix(in_oklab,var(--card),transparent_45%)] py-6 pr-6 pl-7 backdrop-blur-md">
                {/* 左竖线 + 淡引号水印，强化「引用块」观感 */}
                <span
                  aria-hidden="true"
                  className="absolute inset-y-4 left-0 w-[3px] rounded-full bg-[color-mix(in_oklab,var(--primary),transparent_25%)]"
                />
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute top-1 left-5 font-serif text-7xl leading-none text-primary/10 select-none"
                >
                  “
                </span>
                <blockquote className="relative">
                  <p className="text-lg leading-relaxed text-muted-foreground sm:text-xl">
                    人类文明的突破不是因为某个人变得更聪明，
                    <br />
                    而是因为我们学会了分工与协作。
                  </p>
                  <p className="mt-2 text-lg leading-relaxed text-foreground/85 sm:text-xl">
                    AI 的下一步，不是更聪明的个体，
                    <span className="text-gradient font-medium">而是更好的协作。</span>
                  </p>
                </blockquote>
              </figure>

              <div className="mt-9 flex flex-wrap items-center gap-3">
                <a
                  href={WEB_APP_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-primary"
                >
                  <WebIcon />
                  立即使用 · 网页版
                </a>
                <a href={DOWNLOAD_PAGE_PATH} className="btn btn-ghost">
                  <DownloadIcon />
                  下载客户端
                </a>
                <a
                  href={MOBILE_WEB_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-ghost"
                >
                  手机网页版
                </a>
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                网页版免安装、浏览器即开即用 · 也支持 Windows · macOS 桌面客户端与{" "}
                <a
                  href={MOBILE_WEB_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline-offset-2 hover:text-foreground hover:underline"
                >
                  手机浏览器
                </a>
              </p>
            </div>

            {/* 右侧：一次协作的竖向流程图（用图展示；文字版讲解见下方「一次协作的全过程」步骤区 #how） */}
            <div
              className="float-in w-full lg:justify-self-end"
              style={{ animationDelay: "120ms" }}
            >
              <div className="surface mx-auto w-full max-w-[440px] p-5 backdrop-blur-md sm:p-6">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <p className="eyebrow">
                    <Dot />
                    一次任务 · 概览
                  </p>
                  <a
                    href="#how"
                    className="shrink-0 text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    看完整流程 →
                  </a>
                </div>
                <HeroFlow />
                <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                  <span className="inline-flex shrink-0 items-center gap-1.5">
                    <svg
                      width="22"
                      height="8"
                      viewBox="0 0 22 8"
                      aria-hidden="true"
                    >
                      <line
                        x1="1"
                        y1="4"
                        x2="15"
                        y2="4"
                        stroke="var(--primary)"
                        strokeOpacity={0.7}
                        strokeWidth={1.6}
                      />
                      <polygon
                        points="15,1 21,4 15,7"
                        fill="var(--primary)"
                        fillOpacity={0.7}
                      />
                    </svg>
                    任务流向
                  </span>
                  <span className="inline-flex shrink-0 items-center gap-1.5">
                    <svg
                      width="22"
                      height="8"
                      viewBox="0 0 22 8"
                      aria-hidden="true"
                    >
                      <line
                        x1="4"
                        y1="4"
                        x2="18"
                        y2="4"
                        stroke="var(--brand-2)"
                        strokeOpacity={0.6}
                        strokeWidth={1.6}
                        strokeDasharray="4 3"
                      />
                      <circle
                        cx="2"
                        cy="4"
                        r="1.8"
                        fill="var(--brand-2)"
                        fillOpacity={0.75}
                      />
                      <circle
                        cx="20"
                        cy="4"
                        r="1.8"
                        fill="var(--brand-2)"
                        fillOpacity={0.75}
                      />
                    </svg>
                    协作通信
                  </span>
                  <span className="min-w-0">波次 ①并行 ②依赖 ③辩论</span>
                </div>
              </div>
            </div>
          </div>

          {/* 首屏底部渐隐，平滑过渡到下一区块。 */}
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-b from-transparent to-background"
          />
        </section>

        {/* ── 如何协作（步骤）：原 #how 区精简为文字步骤，完整协作图已上移至 Hero 右侧 ── */}
        <section id="how" className="border-t border-border/60 py-20">
          <div className="container-x">
            <Reveal>
              <p className="eyebrow">
                <Dot />
                一次任务的全过程
              </p>
              <h2 className="mt-3 text-3xl font-bold leading-snug sm:text-4xl">
                从一句话，到一支团队的产出
              </h2>
            </Reveal>
            <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              {STEPS.map((s, i) => (
                <Reveal key={s.no} delay={i * 90}>
                  <div className="surface surface-hover h-full p-6">
                    <span className="font-mono text-sm text-primary">{s.no}</span>
                    <h3 className="mt-2 text-lg font-semibold">{s.title}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                      {s.body}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ── 痛点转场 ── */}
        <section className="border-t border-border/60 py-24">
          <div className="container-x grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
            <Reveal>
              <p className="eyebrow">
                <Dot />
                为什么需要一支团队
              </p>
              <h2 className="mt-4 text-3xl font-bold leading-snug sm:text-4xl">
                一个再聪明的助手，
                <br className="hidden sm:block" />
                也只是一个人在战斗
              </h2>
              <p className="mt-6 max-w-xl text-base leading-relaxed text-muted-foreground">
                你让 AI 做一份竞品分析——它搜资料、写大纲、填内容，全是同一个"人"。
                没有人帮它查漏，没有人跟它争论，没有人审它的结论。
                它自己出题、自己答、自己打分。
              </p>
              <p className="mt-4 max-w-xl text-lg leading-relaxed text-muted-foreground">
                可现实里的复杂工作，从来不是靠一个人更努力，而是靠一支会分工、会协商、会互相把关的团队。
              </p>
            </Reveal>
            <Reveal delay={120}>
              <div className="grid gap-4">
                <div className="surface p-6">
                  <p className="text-sm font-semibold text-muted-foreground">
                    其它 AI 产品
                  </p>
                  <p className="mt-2 text-lg font-medium">一个助手，串起所有事</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    上下文越堆越长，角色互相打架，过程不可见。
                  </p>
                </div>
                <div className="surface surface-hover p-6 ring-1 ring-[color-mix(in_oklab,var(--primary),transparent_60%)]">
                  <p className="text-sm font-semibold text-primary">AgentCore</p>
                  <p className="mt-2 text-lg font-medium">一支团队，各司其职</p>
                  <p className="mt-2 text-sm text-muted-foreground">
                    每个 Agent 专注一件事，并行推进、彼此互审，你全程看得见。
                  </p>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ── 核心价值 ── */}
        <section id="value" className="border-t border-border/60 py-24">
          <div className="container-x">
            <Reveal>
              <p className="eyebrow">
                <Dot />
                核心能力
              </p>
              <h2 className="mt-4 max-w-2xl text-3xl font-bold leading-snug sm:text-4xl">
                多 Agent 协作 · 全程可见 · 你是领导者
              </h2>
            </Reveal>
            <div className="mt-12 grid gap-5 md:grid-cols-3">
              {VALUES.map((v, i) => (
                <Reveal key={v.title} delay={i * 110}>
                  <div className="surface surface-hover h-full p-7">
                    <span className="text-sm font-mono text-primary">
                      0{i + 1}
                    </span>
                    <h3 className="mt-3 text-xl font-semibold">{v.title}</h3>
                    <p className="mt-3 text-[0.95rem] leading-relaxed text-muted-foreground">
                      {v.body}
                    </p>
                  </div>
                </Reveal>
              ))}
            </div>
            <Reveal delay={120}>
              <div className="mt-10 flex flex-wrap items-center gap-2.5">
                <span className="text-sm text-muted-foreground">开箱即用：</span>
                {CAPABILITIES.map((c) => (
                  <span key={c} className="pill">
                    {c}
                  </span>
                ))}
              </div>
            </Reveal>
          </div>
        </section>

        {/* ── 角色升级 ── */}
        <section className="border-t border-border/60 py-24">
          <div className="container-x grid items-center gap-12 lg:grid-cols-[0.9fr_1.1fr]">
            <Reveal>
              <p className="eyebrow">
                <Dot />
                你与 AI 的关系
              </p>
              <h2 className="mt-4 text-3xl font-bold leading-snug sm:text-4xl">
                从使用者，
                <br />
                到领导者
              </h2>
              <p className="mt-6 max-w-md text-lg leading-relaxed text-muted-foreground">
                AgentCore 重新定义你和 AI 的关系。你不是在「用」一个工具，而是在「带」一支团队。
              </p>
            </Reveal>
            <Reveal delay={120}>
              <div className="grid gap-3">
                {ROLES.map((r) => (
                  <div
                    key={r.product}
                    className={`flex items-center justify-between rounded-xl border p-5 ${
                      r.highlight
                        ? "border-[color-mix(in_oklab,var(--primary),transparent_50%)] bg-[color-mix(in_oklab,var(--primary),transparent_88%)]"
                        : "border-border bg-[color-mix(in_oklab,var(--card),transparent_25%)]"
                    }`}
                  >
                    <span
                      className={`font-medium ${r.highlight ? "text-foreground" : "text-muted-foreground"}`}
                    >
                      {r.product}
                    </span>
                    <span
                      className={`text-sm font-semibold ${r.highlight ? "text-primary" : "text-muted-foreground"}`}
                    >
                      {r.was}
                    </span>
                  </div>
                ))}
              </div>
              <p className="mt-5 text-base leading-relaxed text-muted-foreground">
                用 ChatGPT 你得学会"怎么问"。用 AgentCore，你只需要知道<span className="font-medium text-foreground">"要什么"</span>。
              </p>
            </Reveal>
          </div>
        </section>

        {/* ── 对比 ── */}
        <section id="compare" className="border-t border-border/60 py-24">
          <div className="container-x">
            <Reveal>
              <p className="eyebrow">
                <Dot />
                单 Agent 助手 vs 协作平台
              </p>
              <h2 className="mt-4 max-w-2xl text-3xl font-bold leading-snug sm:text-4xl">
                架构不同，结果就不同
              </h2>
            </Reveal>
            <Reveal delay={100}>
              <div className="surface mt-12 overflow-x-auto">
                <table className="w-full min-w-[640px] border-collapse text-left">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="p-5 text-sm font-semibold text-muted-foreground">
                        &nbsp;
                      </th>
                      <th className="p-5 text-sm font-semibold text-muted-foreground">
                        单 Agent 助手
                      </th>
                      <th className="p-5 text-sm font-semibold text-primary">
                        AgentCore
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {COMPARE.map((row) => (
                      <tr
                        key={row.dim}
                        className="border-b border-border/50 last:border-0"
                      >
                        <td className="p-5 text-sm font-medium">{row.dim}</td>
                        <td className="p-5 text-sm text-muted-foreground">
                          {row.others}
                        </td>
                        <td className="p-5 text-sm font-medium text-foreground">
                          {row.ours}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ── 生态 ── */}
        <section id="ecosystem" className="border-t border-border/60 py-24">
          <div className="container-x">
            <Reveal>
              <div className="flex flex-wrap items-center gap-3">
                <p className="eyebrow">
                  <Dot />
                  扩展生态
                </p>
                <span className="pill border-[color-mix(in_oklab,var(--warning),transparent_60%)] text-warning">
                  即将开放
                </span>
              </div>
              <h2 className="mt-4 max-w-2xl text-3xl font-bold leading-snug sm:text-4xl">
                不止一个 Agent，而是一整套生态
              </h2>
              <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">
                把你打磨好的工作流和团队，沉淀成五类可复用的资产——自己用，或分享给别人。
              </p>
            </Reveal>
            <div className="mt-10 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              {ECOSYSTEM.map((a, i) => (
                <Reveal key={a.name} delay={i * 70}>
                  <div className="surface surface-hover flex h-full min-h-[7rem] flex-col items-center justify-center gap-2 p-5 text-center">
                    <span className="text-base font-semibold">{a.name}</span>
                    <span className="text-xs leading-snug text-muted-foreground">{a.desc}</span>
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ── 结尾 ── */}
        <section className="border-t border-border/60 py-28">
          <div className="container-x text-center">
            <Reveal>
              <h2 className="mx-auto max-w-3xl text-4xl font-bold leading-tight sm:text-5xl">
                <span className="text-gradient">协作，是更高级的智能。</span>
              </h2>
              <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground">
                AgentCore —— 让 AI 像团队一样工作。
              </p>
              <div className="mx-auto mt-6 flex flex-wrap items-center justify-center gap-2.5">
                <span className="pill">MCP 工具协议</span>
                <span className="pill">可私有部署</span>
                <span className="pill">网页 + 桌面 + 手机</span>
              </div>
              <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
                <a
                  href={WEB_APP_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-primary"
                >
                  <WebIcon />
                  立即使用 · 网页版
                </a>
                <a href={DOWNLOAD_PAGE_PATH} className="btn btn-ghost">
                  <DownloadIcon />
                  下载客户端
                </a>
                <a
                  href={MOBILE_WEB_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-ghost"
                >
                  手机网页版
                </a>
              </div>
            </Reveal>
          </div>
        </section>
      </main>

      {/* ── 页脚 ── */}
      <footer className="border-t border-border/60 py-14">
        <div className="container-x flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-xs">
            <div className="flex items-center gap-2.5">
              <BrandMark />
              <span className="text-base font-bold">AgentCore</span>
            </div>
            <p className="mt-3 text-sm text-muted-foreground">
              协作智能平台。让多个 AI Agent 像团队一样分工、协商、互审，共同完成复杂任务。
            </p>
          </div>
          <div className="grid grid-cols-2 gap-10 text-sm sm:grid-cols-3">
            <div>
              <p className="font-semibold">产品</p>
              <ul className="mt-3 space-y-2 text-muted-foreground">
                <li>
                  <a
                    href={WEB_APP_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-foreground"
                  >
                    网页版
                  </a>
                </li>
                <li>
                  <a href={DOWNLOAD_PAGE_PATH} className="hover:text-foreground">
                    下载客户端
                  </a>
                </li>
                <li>
                  <a
                    href={MOBILE_WEB_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-foreground"
                  >
                    手机网页版
                  </a>
                </li>
                <li>
                  <a href="#value" className="hover:text-foreground">
                    核心能力
                  </a>
                </li>
                <li>
                  <a href="#how" className="hover:text-foreground">
                    团队流程
                  </a>
                </li>
                <li>
                  <a href="#compare" className="hover:text-foreground">
                    产品对比
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <p className="font-semibold">理念</p>
              <ul className="mt-3 space-y-2 text-muted-foreground">
                <li>
                  <a href="#top" className="hover:text-foreground">
                    核心理念
                  </a>
                </li>
                <li>
                  <a href="#ecosystem" className="hover:text-foreground">
                    扩展生态
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <p className="font-semibold">关于</p>
              <ul className="mt-3 space-y-2 text-muted-foreground">
                <li>面向大众的 Multi-Agent AI 工作台</li>
              </ul>
            </div>
          </div>
        </div>
        <div className="container-x mt-10 border-t border-border/50 pt-6 text-sm text-muted-foreground">
          © 2026 AgentCore · 协作智能平台
        </div>
      </footer>
    </div>
  );
}
