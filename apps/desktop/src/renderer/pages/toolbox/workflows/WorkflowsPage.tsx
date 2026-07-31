import { PageContainer } from "@/components/layout/PageContainer";
import { Button, Card } from "@/components/ui";
import { notifyError, notifySuccess } from "@/lib/toast";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { ApiError } from "@/services/api";
import { emptyWorkflowDefinition } from "@/services/workflowDefinition";
import {
  type UserWorkflow,
  type WorkflowTemplate,
  createWorkflow,
  deleteWorkflow,
  isWorkflowBackendUnavailable,
  listWorkflowTemplates,
  listWorkflows,
} from "@/services/workflows";
import {
  ChevronLeft,
  Copy,
  Loader2,
  Pencil,
  Play,
  Plus,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { RunWorkflowDialog } from "./RunWorkflowDialog";
import { UseTemplateDialog } from "./UseTemplateDialog";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

function formatUpdated(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

/**
 * 工具箱 · 工作流列表（高级资产入口）。
 * 两区：官方模板（只读 · 使用=复制为我的） / 我的工作流（编辑/跑/删）。
 */
export function WorkflowsPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<UserWorkflow[] | null>(null);
  const [templates, setTemplates] = useState<WorkflowTemplate[] | null>(null);
  const [templatesHint, setTemplatesHint] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [localBanner, setLocalBanner] = useState(false);
  const [runTarget, setRunTarget] = useState<UserWorkflow | null>(null);
  const [useTarget, setUseTarget] = useState<WorkflowTemplate | null>(null);

  const loadMine = useCallback(async () => {
    setListError(null);
    try {
      const list = await listWorkflows();
      setItems(list);
      setLocalBanner(
        isWorkflowBackendUnavailable() || list.some((w) => w.localOnly),
      );
    } catch (e) {
      setListError(errMsg(e, "加载工作流失败"));
      setItems([]);
    }
  }, []);

  const loadTemplates = useCallback(async () => {
    setTemplatesHint(null);
    try {
      const list = await listWorkflowTemplates();
      setTemplates(list);
      // Empty after a successful call = backend ready but catalog empty, or 404
      // degraded to []. Hide section when empty (see render).
    } catch (e) {
      // Non-404 failures: keep「我的」 intact; soft tip only.
      setTemplates([]);
      setTemplatesHint(errMsg(e, "官方模板暂时不可用"));
    }
  }, []);

  useEffect(() => {
    void loadMine();
    void loadTemplates();
  }, [loadMine, loadTemplates]);

  const onCreate = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const created = await createWorkflow({
        name: "未命名工作流",
        definition: emptyWorkflowDefinition(),
      });
      notifySuccess(created.localOnly ? "已建本地草稿" : "已创建");
      navigate(APP_PATHS.toolbox.workflows.edit(created.id));
    } catch (e) {
      notifyError(e, "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (w: UserWorkflow) => {
    if (!window.confirm(`确定删除「${w.name}」？`)) return;
    setBusyId(w.id);
    try {
      await deleteWorkflow(w.id);
      setItems((prev) => (prev ?? []).filter((x) => x.id !== w.id));
      notifySuccess("已删除");
    } catch (e) {
      notifyError(e, "删除失败");
    } finally {
      setBusyId(null);
    }
  };

  const showOfficial =
    templates !== null && (templates.length > 0 || !!templatesHint);

  return (
    <PageContainer width="canvas">
      <Button
        variant="ghost"
        onClick={() => navigate("/toolbox")}
        className="mb-4 h-auto gap-1 px-0 py-0 text-sm text-muted-foreground hover:text-foreground"
        icon={<ChevronLeft size={16} />}
      >
        工具箱
      </Button>

      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">工作流</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            可保存的团队拆法：画布定义队员步骤与等人关卡，开跑时强制按图执行。
          </p>
        </div>
        <Button
          size="md"
          disabled={creating}
          icon={
            creating ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Plus size={14} />
            )
          }
          onClick={() => void onCreate()}
        >
          新建工作流
        </Button>
      </header>

      {localBanner && (
        <p className="mt-4 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          后端工作流 API
          尚未就绪：列表与编辑走浏览器本地草稿；「跑一次」需等后端合入。
        </p>
      )}

      {listError && (
        <p className="mt-4 text-sm text-destructive">{listError}</p>
      )}

      {showOfficial && (
        <section className="mt-6 space-y-3">
          <p className="text-xs font-medium text-muted-foreground">官方模板</p>
          {templatesHint && (
            <p className="text-xs text-muted-foreground">{templatesHint}</p>
          )}
          {templates?.map((tpl) => (
            <Card key={tpl.id} className="px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Sparkles size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-foreground">
                      {tpl.title}
                    </p>
                    <span className="rounded-lg bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                      官方
                    </span>
                  </div>
                  {tpl.summary ? (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {tpl.summary}
                    </p>
                  ) : null}
                </div>
                <Button
                  size="md"
                  variant="neutral"
                  icon={<Copy size={14} />}
                  onClick={() => setUseTarget(tpl)}
                >
                  使用
                </Button>
              </div>
            </Card>
          ))}
        </section>
      )}

      <section className="mt-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-xs font-medium text-muted-foreground">
            我的工作流
          </p>
        </div>
        <div className="space-y-3">
          {items === null ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 size={16} className="animate-spin" />
              加载中…
            </div>
          ) : items.length === 0 ? (
            <Card className="p-6 text-sm text-muted-foreground">
              还没有工作流。可从上方官方模板「使用」复制一份，或新建空白图；保存后可手动跑一次，或到「自动化」里绑定站立任务。
            </Card>
          ) : (
            items.map((w) => {
              const stepCount = w.definition.nodes.filter(
                (n) => n.kind === "agent_step",
              ).length;
              const gateCount = w.definition.nodes.filter(
                (n) => n.kind === "human_gate",
              ).length;
              const busy = busyId === w.id;
              return (
                <Card
                  key={w.id}
                  className="flex flex-wrap items-center gap-3 p-4"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">
                      {w.name}
                      {w.localOnly ? (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          本地草稿
                        </span>
                      ) : null}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {stepCount} 步骤 · {gateCount} 关卡 · v{w.version} · 更新{" "}
                      {formatUpdated(w.updatedAt)}
                    </p>
                    {w.description ? (
                      <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                        {w.description}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Button
                      variant="neutral"
                      size="sm"
                      icon={<Play size={14} />}
                      disabled={busy}
                      onClick={() => setRunTarget(w)}
                    >
                      跑一次
                    </Button>
                    <Button
                      variant="neutral"
                      size="sm"
                      icon={<Pencil size={14} />}
                      disabled={busy}
                      onClick={() =>
                        navigate(APP_PATHS.toolbox.workflows.edit(w.id))
                      }
                    >
                      编辑
                    </Button>
                    <Button
                      variant="neutral"
                      size="sm"
                      icon={
                        busy ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Trash2 size={14} />
                        )
                      }
                      disabled={busy}
                      onClick={() => void onDelete(w)}
                    >
                      删除
                    </Button>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      </section>

      {runTarget && (
        <RunWorkflowDialog
          open
          workflowId={runTarget.id}
          workflowName={runTarget.name}
          onClose={() => setRunTarget(null)}
        />
      )}

      <UseTemplateDialog
        open={!!useTarget}
        template={useTarget}
        onClose={() => setUseTarget(null)}
      />
    </PageContainer>
  );
}
