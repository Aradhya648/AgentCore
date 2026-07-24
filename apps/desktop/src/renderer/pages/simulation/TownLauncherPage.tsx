import { PageContainer } from "@/components/layout/PageContainer";
import { Button, Card, SectionLabel } from "@/components/ui";
import { describeError } from "@/lib/errors";
import { cn } from "@/lib/utils";
import { createSimulationRun } from "@/services/simulation/api";
import { OpenInAgentTownButton } from "@/simulation/OpenInAgentTownButton";
import {
  type SavedSimulationRun,
  listSavedRuns,
  rememberRun,
} from "@/simulation/runHistory";
import type { SimulationRunView } from "@/simulation/runModel";
import { runStatusLabel } from "@/simulation/runStatus";
import { useSimulationUiStore } from "@/simulation/store/simulationStore";
import { ArrowLeft, ChevronDown, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

/**
 * DT-01: Desktop launcher for AgentTown (spawn exe + session.json).
 * 3D observation lives in the Unity client — no embedded R3F.
 */

function shortRunId(id: string): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

function scenarioLabel(scenario: string): string {
  if (scenario === "town") return "小镇";
  return scenario;
}

/** Status tone for launcher UI — running→primary, completed→success, else muted. */
function statusDotClass(status: string | undefined): string {
  if (status === "running") return "bg-primary";
  if (status === "completed") return "bg-success";
  return "bg-muted-foreground";
}

function statusTextClass(status: string | undefined): string {
  if (status === "running") return "text-primary";
  if (status === "completed") return "text-success";
  return "text-muted-foreground";
}

function formatClockHour(hour: number): string {
  return `${String(Math.max(0, Math.floor(hour)) % 24).padStart(2, "0")}:00`;
}

function relativeSavedAt(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms) || ms < 0) return "刚刚";
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const d = Math.floor(hr / 24);
  return `${d} 天前`;
}

function StatusDot({ status }: { status: string | undefined }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn("size-1.5 shrink-0 rounded-full", statusDotClass(status))}
        aria-hidden
      />
      <span className={cn("text-xs font-medium", statusTextClass(status))}>
        {runStatusLabel(status)}
      </span>
    </span>
  );
}

function RunMetaLine({
  tick,
  hour,
  savedAt,
}: {
  tick: number;
  hour: number;
  savedAt?: string;
}) {
  const parts = [`Tick ${tick}`, `时刻 ${formatClockHour(hour)}`];
  if (savedAt) parts.push(relativeSavedAt(savedAt));
  return <p className="text-xs text-muted-foreground">{parts.join(" · ")}</p>;
}

export function TownLauncherPage() {
  const run = useSimulationUiStore((s) => s.run);
  const [savedRuns, setSavedRuns] = useState<SavedSimulationRun[]>([]);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [launchHint, setLaunchHint] = useState<{
    message: string;
    candidates?: string[];
  } | null>(null);

  useEffect(() => {
    setSavedRuns(listSavedRuns());
  }, []);

  const activateRun = (next: SimulationRunView) => {
    useSimulationUiStore.getState().setRun(next);
    rememberRun(next);
    setSavedRuns(listSavedRuns());
  };

  const onCreate = async () => {
    setCreating(true);
    setActionError(null);
    try {
      const created = await createSimulationRun({ scenario: "town" });
      activateRun(created);
    } catch (err) {
      setActionError(describeError(err)?.message ?? "创建小镇失败");
    } finally {
      setCreating(false);
    }
  };

  const onSelectSaved = (saved: SavedSimulationRun) => {
    setActionError(null);
    try {
      activateRun(saved);
    } catch (err) {
      setActionError(describeError(err)?.message ?? "加载小镇失败");
    }
  };

  return (
    <div className="flex h-full w-full min-h-0 flex-col bg-background">
      {/* 1) Top bar — full-bleed border; inner aligned to the same content
          width as the body so the header and content share one left edge. */}
      <header className="shrink-0 border-b border-border">
        <div className="mx-auto flex w-full max-w-4xl items-center gap-3 px-6 py-3">
          <Link
            to="/"
            className="flex shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="返回首页"
            title="返回首页"
          >
            <ArrowLeft size={18} />
          </Link>
          <div className="min-w-0">
            <h1 className="text-sm font-medium text-foreground">AI 小镇</h1>
            <p className="text-xs text-muted-foreground">
              创建或恢复小镇，在 AgentTown 中观看
            </p>
          </div>
        </div>
      </header>

      {/* Body — content-width page shell, centered so the launcher reads as a
          focused column rather than a sparse left-clumped grid. */}
      <PageContainer width="content" className="min-h-0 flex-1">
        <div className="flex flex-col gap-8">
          {/* 2) Hero */}
          <section className="flex flex-col items-start gap-4">
            <p className="max-w-xl text-base text-foreground">
              一座住着 AI 居民的 3D 小镇——创建一个小镇，在 AgentTown
              里实时观看它们生活、社交与决策。
            </p>
            <p className="text-xs text-muted-foreground">
              默认 scripted 模式，无需配置 DeepSeek 即可本地观看。
            </p>
            <div className="flex flex-col items-start gap-2">
              <Button
                variant="primary"
                size="md"
                disabled={creating}
                icon={<Plus size={14} />}
                onClick={() => void onCreate()}
              >
                {creating ? "创建中…" : "新建小镇"}
              </Button>
              {actionError ? (
                <p className="text-sm text-destructive" role="alert">
                  {actionError}
                </p>
              ) : null}
            </div>
          </section>

          {/* 3) Current town card */}
          {run ? (
            <Card className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0 space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">
                    当前小镇
                  </p>
                  <p className="font-mono text-sm text-foreground">
                    {shortRunId(run.id)}
                  </p>
                  <StatusDot status={run.status} />
                  <RunMetaLine tick={run.tick} hour={run.hour} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <OpenInAgentTownButton
                    runId={run.id}
                    size="md"
                    variant="primary"
                    onLaunchError={setLaunchHint}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      useSimulationUiStore.getState().resetSession();
                      setLaunchHint(null);
                    }}
                  >
                    退出当前 Run
                  </Button>
                </div>
              </div>
            </Card>
          ) : null}

          {/* Launch failure detail */}
          {launchHint ? (
            <div
              className="rounded-xl border border-destructive/40 bg-card p-4"
              role="alert"
            >
              <p className="text-sm text-foreground whitespace-pre-wrap">
                {launchHint.message}
              </p>
              {launchHint.candidates && launchHint.candidates.length > 0 ? (
                <div className="mt-3">
                  <p className="text-xs font-medium text-muted-foreground">
                    解析到的候选路径
                  </p>
                  <ul className="mt-1 list-inside list-disc break-all text-xs text-muted-foreground">
                    {launchHint.candidates.map((path) => (
                      <li key={path}>{path}</li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs text-muted-foreground">
                    建议：先跑{" "}
                    <code className="rounded-lg bg-muted px-1">
                      pnpm town:build
                    </code>
                    ，或设置环境变量{" "}
                    <code className="rounded-lg bg-muted px-1">
                      AGENTTOWN_PATH
                    </code>{" "}
                    指向可执行文件。
                  </p>
                </div>
              ) : null}
            </div>
          ) : null}

          {/* 4) Recent towns */}
          <section className="space-y-3">
            <div className="flex items-baseline justify-between gap-2">
              <SectionLabel>最近的小镇</SectionLabel>
              <span className="text-xs text-muted-foreground">
                {savedRuns.length} 条
              </span>
            </div>

            {savedRuns.length === 0 ? (
              <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
                还没有小镇，点「新建小镇」开始吧
              </p>
            ) : (
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {savedRuns.map((saved) => {
                  const isActive = run?.id === saved.id;
                  return (
                    <li key={saved.id}>
                      <Card
                        variant="interactive"
                        aria-current={isActive ? "true" : undefined}
                        className={cn(
                          "flex h-full flex-col",
                          isActive && "border-primary/40",
                        )}
                      >
                        <button
                          type="button"
                          className="min-w-0 flex-1 space-y-1 p-4 text-left"
                          onClick={() => onSelectSaved(saved)}
                        >
                          <p className="text-sm font-medium text-foreground">
                            {scenarioLabel(saved.scenario)}
                          </p>
                          <p className="font-mono text-xs text-muted-foreground">
                            {shortRunId(saved.id)}
                          </p>
                          <StatusDot status={saved.status} />
                          <RunMetaLine
                            tick={saved.tick}
                            hour={saved.hour}
                            savedAt={saved.savedAt}
                          />
                        </button>
                        <div className="px-4 pb-4">
                          <OpenInAgentTownButton
                            runId={saved.id}
                            size="sm"
                            variant="neutral"
                            onLaunchError={setLaunchHint}
                          />
                        </div>
                      </Card>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* 5) Developer tips (de-emphasized) */}
          <details className="group border-t border-border pt-4">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs text-muted-foreground [&::-webkit-details-marker]:hidden">
              <ChevronDown
                size={12}
                className="shrink-0 transition-transform group-open:rotate-180"
                aria-hidden
              />
              开发者提示
            </summary>
            <div className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              <p>需本机安装 AgentTown.exe 才能从桌面拉起客户端。</p>
              <p>
                在仓库根目录执行{" "}
                <code className="rounded-lg bg-muted px-1">
                  pnpm town:build
                </code>{" "}
                生成{" "}
                <code className="rounded-lg bg-muted px-1">
                  apps/town/Builds/Windows/AgentTown.exe
                </code>
                ；也可设置环境变量{" "}
                <code className="rounded-lg bg-muted px-1">AGENTTOWN_PATH</code>{" "}
                指向可执行文件。
              </p>
            </div>
          </details>
        </div>
      </PageContainer>
    </div>
  );
}
