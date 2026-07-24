import { PageContainer } from "@/components/layout/PageContainer";
import {
  Badge,
  Button,
  Card,
  CatalogIconShell,
  SectionLabel,
} from "@/components/ui";
import { type ArtifactKind, artifactColorVar } from "@/lib/catalogColors";
import { cn } from "@/lib/utils";
import {
  AppWindow,
  BookOpen,
  Building2,
  ChevronRight,
  FileText,
  FormInput,
  GitBranch,
  type LucideIcon,
  Network,
  Palette,
  Plug,
  Presentation,
  ScrollText,
  Table2,
  Workflow,
  Wrench,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

interface ToolboxEntry {
  id: string;
  title: string;
  description: string;
  icon: LucideIcon;
  color: ArtifactKind;
  /** 可用项点击跳转的子路由；占位（即将上线）项不设。 */
  to?: string;
}

/** 了解平台：产品手册入口，与能力项同视觉语言，靠首组位置区分。 */
const MANUAL: ToolboxEntry = {
  id: "manual",
  title: "产品手册",
  description: "从上手到玩转，到看懂团队怎么运转",
  icon: BookOpen,
  color: "manual",
  to: "/toolbox/manual",
};

const CREATION_TOOLS: ToolboxEntry[] = [
  {
    id: "doc",
    title: "文档",
    description: "在线 Markdown，AI 协同写作",
    icon: FileText,
    color: "doc",
  },
  {
    id: "mindmap",
    title: "思维导图",
    description: "结构化梳理想法与大纲",
    icon: Network,
    color: "mindmap",
  },
  {
    id: "table",
    title: "多维表格",
    description: "结构化数据与多视图",
    icon: Table2,
    color: "table",
  },
  {
    id: "canvas",
    title: "白板",
    description: "自由排布、人与 AI 同板协作",
    icon: Palette,
    color: "canvas",
    to: "/whiteboard",
  },
  {
    id: "slides",
    title: "幻灯片",
    description: "AI 生成可编辑演示",
    icon: Presentation,
    color: "slides",
  },
  {
    id: "app",
    title: "可运行产物",
    description: "HTML / React 即时预览",
    icon: AppWindow,
    color: "app",
  },
  {
    id: "diagram",
    title: "流程图",
    description: "流程 / 架构 / 时序图",
    icon: GitBranch,
    color: "diagram",
  },
  {
    id: "form",
    title: "表单",
    description: "收集数据并汇入表格",
    icon: FormInput,
    color: "form",
  },
];

// 「能力」组：AI 自身的能力（工具 + AI 提示词，均已可用、点开见对应能力图鉴）+
// 平台集成（连接器 / 工作流，即将开放）。能力图鉴只分两类——工具（确定性代码）与
// AI 提示词（含准则与按需注入的工具进阶用法 / 薄技能）；这批薄技能本质是 Prompt 注入、不是
// 独立能力，并入「AI 提示词」页。
const CAPABILITIES: ToolboxEntry[] = [
  {
    id: "tools",
    title: "工具",
    description: "Agent 可调用的动作工具，含可用性与调用参数",
    icon: Wrench,
    color: "tools",
    to: "/toolbox/tools",
  },
  {
    id: "guidelines",
    title: "AI 提示词",
    description:
      "AI 遵循的提示词：全员准则 + CEO 完整提示词 + 工具进阶用法（薄技能）",
    icon: ScrollText,
    color: "guidelines",
    to: "/toolbox/guidelines",
  },
  {
    id: "connectors",
    title: "集成 · 连接器",
    description: "MCP 与第三方服务接入",
    icon: Plug,
    color: "connectors",
  },
  {
    id: "workflow",
    title: "工作流",
    description: "编排工具与 Agent 协作流程",
    icon: Workflow,
    color: "workflow",
  },
];

/** DEV-only 实验入口：MVP 观测面暂不占侧栏一级导航，收纳于此。生产构建整组剥离。 */
const EXPERIMENTS: ToolboxEntry[] = import.meta.env.DEV
  ? [
      {
        id: "ai-town",
        title: "AI 小镇",
        description: "启动 AgentTown 3D 观测客户端",
        icon: Building2,
        color: "app",
        to: "/simulation/town",
      },
    ]
  : [];

const TOOLBOX_TILE_GRID =
  "grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4";

function ToolboxSectionHeader({
  label,
  meta,
  className,
}: {
  label: string;
  meta?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "col-span-full flex items-baseline justify-between gap-3",
        className,
      )}
    >
      <SectionLabel>{label}</SectionLabel>
      {meta ? (
        <span className="shrink-0 text-xs text-muted-foreground/60">
          {meta}
        </span>
      ) : null}
    </div>
  );
}

function ToolboxTileCard({
  entry,
  comingSoon = false,
}: {
  entry: ToolboxEntry;
  comingSoon?: boolean;
}) {
  const navigate = useNavigate();
  const { icon: Icon, title, description, to, color } = entry;
  const available = Boolean(to);
  const colorVar = artifactColorVar(color);

  const inner = (
    <Card
      className={cn(
        "flex h-full w-full min-w-0 flex-col gap-3 p-4",
        available && "shadow-sm transition-shadow group-hover:shadow-md",
      )}
      variant={available ? "interactive" : "default"}
    >
      <div className="flex items-start justify-between gap-2">
        <CatalogIconShell colorVar={colorVar} muted={comingSoon}>
          <Icon size={18} />
        </CatalogIconShell>
        {comingSoon ? (
          <Badge tone="muted" pill className="shrink-0">
            即将开放
          </Badge>
        ) : available ? (
          <ChevronRight
            size={14}
            className="mt-0.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground"
          />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-medium text-foreground">{title}</h3>
        <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {description}
        </p>
      </div>
    </Card>
  );

  if (!to) {
    return inner;
  }

  return (
    <Button
      variant="ghost"
      onClick={() => navigate(to)}
      className="group !flex h-full w-full min-w-0 flex-col items-stretch justify-start p-0 text-left font-normal"
    >
      {inner}
    </Button>
  );
}

export function ToolboxPage() {
  return (
    <PageContainer width="canvas">
      <header className="pb-2">
        <h1 className="text-xl font-semibold text-foreground">工具箱</h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          AI 工具与创作工具，人与 Agent 协同的能力中心
        </p>
      </header>

      <div className={cn("mt-8", TOOLBOX_TILE_GRID)}>
        <ToolboxSectionHeader label="了解平台" />
        <ToolboxTileCard entry={MANUAL} />

        <ToolboxSectionHeader
          className="mt-6"
          label="能力"
          meta={`${CAPABILITIES.filter((e) => e.to).length} 项可用`}
        />
        {CAPABILITIES.map((entry) => (
          <ToolboxTileCard
            key={entry.id}
            entry={entry}
            comingSoon={!entry.to}
          />
        ))}

        <ToolboxSectionHeader
          className="mt-6"
          label="创作工具"
          meta={`${CREATION_TOOLS.length} 项`}
        />
        {CREATION_TOOLS.map((entry) => (
          <ToolboxTileCard
            key={entry.id}
            entry={entry}
            comingSoon={!entry.to}
          />
        ))}

        {EXPERIMENTS.length > 0 ? (
          <>
            <ToolboxSectionHeader className="mt-6" label="实验" meta="开发期" />
            {EXPERIMENTS.map((entry) => (
              <ToolboxTileCard key={entry.id} entry={entry} />
            ))}
          </>
        ) : null}
      </div>
    </PageContainer>
  );
}
