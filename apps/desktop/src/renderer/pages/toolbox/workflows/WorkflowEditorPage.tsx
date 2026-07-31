import { PageContainer } from "@/components/layout/PageContainer";
import { Button, Input } from "@/components/ui";
import { notifyError, notifySuccess } from "@/lib/toast";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { ApiError } from "@/services/api";
import {
  type WorkflowDefinition,
  validateWorkflowDefinition,
} from "@/services/workflowDefinition";
import {
  type UserWorkflow,
  getWorkflow,
  isWorkflowBackendUnavailable,
  patchWorkflow,
} from "@/services/workflows";
import { ChevronLeft, Loader2, Play, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { RunWorkflowDialog } from "./RunWorkflowDialog";
import { WorkflowCanvas } from "./WorkflowCanvas";
import { WorkflowNodeInspector } from "./WorkflowNodeInspector";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

/**
 * 工作流定义态画布编辑页（与协作图路由隔离）。
 */
export function WorkflowEditorPage() {
  const { workflowId = "" } = useParams();
  const navigate = useNavigate();
  const [workflow, setWorkflow] = useState<UserWorkflow | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [definition, setDefinition] = useState<WorkflowDefinition | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runOpen, setRunOpen] = useState(false);
  const [localBanner, setLocalBanner] = useState(false);

  const load = useCallback(async () => {
    if (!workflowId) return;
    setLoading(true);
    setError(null);
    try {
      const w = await getWorkflow(workflowId);
      setWorkflow(w);
      setName(w.name);
      setDescription(w.description ?? "");
      setDefinition(w.definition);
      setLocalBanner(!!w.localOnly || isWorkflowBackendUnavailable());
    } catch (e) {
      setError(errMsg(e, "加载工作流失败"));
      setWorkflow(null);
    } finally {
      setLoading(false);
    }
  }, [workflowId]);

  useEffect(() => {
    void load();
  }, [load]);

  const issues = useMemo(
    () => (definition ? validateWorkflowDefinition(definition) : []),
    [definition],
  );

  const save = async () => {
    if (!workflowId || !definition || saving) return;
    if (!name.trim()) {
      setError("请填写名称");
      return;
    }
    if (issues.length > 0) {
      setError(issues[0]?.message ?? "定义校验未通过");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const next = await patchWorkflow(workflowId, {
        name: name.trim(),
        description: description.trim() || null,
        definition,
      });
      setWorkflow(next);
      setLocalBanner(!!next.localOnly || isWorkflowBackendUnavailable());
      notifySuccess(next.localOnly ? "已保存到本地草稿" : "工作流已保存");
    } catch (e) {
      setError(errMsg(e, "保存失败"));
      notifyError(e, "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <PageContainer width="canvas">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin" />
          加载中…
        </div>
      </PageContainer>
    );
  }

  if (!workflow || !definition) {
    return (
      <PageContainer width="canvas">
        <Button
          variant="ghost"
          onClick={() => navigate(APP_PATHS.toolbox.workflows.root)}
          className="mb-4 h-auto gap-1 px-0 py-0 text-sm text-muted-foreground hover:text-foreground"
          icon={<ChevronLeft size={16} />}
        >
          工作流
        </Button>
        <p className="text-sm text-destructive">{error ?? "工作流不存在"}</p>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="canvas" className="flex min-h-0 flex-col pb-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Button
          variant="ghost"
          onClick={() => navigate(APP_PATHS.toolbox.workflows.root)}
          className="h-auto gap-1 px-0 py-0 text-sm text-muted-foreground hover:text-foreground"
          icon={<ChevronLeft size={16} />}
        >
          工作流
        </Button>
        <div className="ml-auto flex flex-wrap gap-2">
          <Button
            variant="neutral"
            size="md"
            icon={<Play size={14} />}
            onClick={() => setRunOpen(true)}
          >
            跑一次
          </Button>
          <Button
            size="md"
            disabled={saving}
            icon={
              saving ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Save size={14} />
              )
            }
            onClick={() => void save()}
          >
            保存
          </Button>
        </div>
      </div>

      {localBanner && (
        <p className="mb-3 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
          后端工作流 API
          尚未就绪：当前以浏览器本地草稿保存；「跑一次」需等后端合入。
        </p>
      )}

      <div className="mb-3 grid gap-3 sm:grid-cols-[1fr_1.2fr]">
        <label className="block" htmlFor="wf-name">
          <span className="mb-1 block text-xs text-muted-foreground">名称</span>
          <Input
            id="wf-name"
            className="w-full"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block" htmlFor="wf-desc">
          <span className="mb-1 block text-xs text-muted-foreground">
            说明（可选）
          </span>
          <Input
            id="wf-desc"
            className="w-full"
            value={description}
            maxLength={400}
            placeholder="可保存的团队拆法"
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
      </div>

      <div className="grid min-h-[520px] flex-1 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="overflow-hidden rounded-xl border border-border bg-background">
          <WorkflowCanvas
            definition={definition}
            selectedId={selectedId}
            onChange={setDefinition}
            onSelect={setSelectedId}
            className="h-[520px] lg:h-full"
          />
        </div>
        <div className="overflow-y-auto rounded-xl border border-border bg-background">
          <WorkflowNodeInspector
            definition={definition}
            selectedId={selectedId}
            onChange={setDefinition}
          />
        </div>
      </div>

      {issues.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-warning">
          {issues.slice(0, 4).map((issue) => (
            <li key={`${issue.code}-${issue.nodeId ?? ""}`}>{issue.message}</li>
          ))}
        </ul>
      )}
      {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
      <p className="mt-2 text-xs text-muted-foreground">
        v{workflow.version}
        {workflow.localOnly ? " · 本地草稿" : ""}
      </p>

      <RunWorkflowDialog
        open={runOpen}
        workflowId={workflow.id}
        workflowName={name.trim() || workflow.name}
        onClose={() => setRunOpen(false)}
      />
    </PageContainer>
  );
}
