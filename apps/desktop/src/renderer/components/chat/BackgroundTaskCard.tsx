import {
  Badge,
  type BadgeTone,
  Button,
  Card,
  PatternCardHeader,
} from "@/components/ui";
import { statusCardChrome } from "@/components/ui/tone-presets";
import type { HandoffJob } from "@/services/handoff";
import {
  AlertTriangle,
  CheckCircle2,
  Cloud,
  GitPullRequest,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { BackgroundTaskReview } from "./BackgroundTaskReview";
import { Markdown } from "./Markdown";

export function BackgroundTaskCard({
  job,
  rootId,
}: {
  job: HandoffJob;
  rootId: string | null;
}) {
  const meta = STATUS_META[job.status];

  return (
    <Card
      className={`animate-task-card-enter p-3 ${meta.border} ${meta.surface}`}
    >
      <PatternCardHeader
        icon={<Cloud size={16} />}
        iconClassName={meta.accent}
        label="后台云端任务"
        labelClassName={meta.accent}
        badge={<StatusBadge job={job} />}
        trailing={formatWhen(job.createdAt)}
      />
      <div className="mt-1 break-words">
        <Markdown content={job.task} />
      </div>
      <Body job={job} rootId={rootId} />
    </Card>
  );
}

function Body({ job, rootId }: { job: HandoffJob; rootId: string | null }) {
  const [reviewing, setReviewing] = useState(false);

  if (job.status === "pending") {
    return (
      <p className="mt-1.5 text-xs text-muted-foreground">
        正在打包本地文件并派发到云端…
      </p>
    );
  }
  if (job.status === "running") {
    return (
      <p className="mt-1.5 text-xs text-muted-foreground">
        云端团队正在后台处理，完成后会在这里通知你。
      </p>
    );
  }
  if (job.status === "failed") {
    return (
      <p className="mt-1.5 text-xs text-destructive">
        {job.error ? `失败：${job.error}` : "任务失败"}
      </p>
    );
  }

  if (!rootId) {
    return (
      <p className="mt-1.5 text-xs text-muted-foreground">
        已完成 · 切到本地模式后可在此查看并应用结果。
      </p>
    );
  }
  if (reviewing) {
    return (
      <BackgroundTaskReview
        conversationId={job.sourceConversationId}
        jobId={job.id}
        rootId={rootId}
        onClose={() => setReviewing(false)}
      />
    );
  }
  return (
    <div className="mt-2">
      <Button
        variant="neutral"
        className="border border-border"
        icon={<GitPullRequest size={13} />}
        onClick={() => setReviewing(true)}
      >
        查看并应用
      </Button>
    </div>
  );
}

function StatusBadge({ job }: { job: HandoffJob }) {
  const meta = STATUS_META[job.status];
  const tone: BadgeTone =
    job.status === "running"
      ? "primary"
      : job.status === "succeeded"
        ? "success"
        : job.status === "failed"
          ? "destructive"
          : "muted";

  return (
    <Badge tone={tone} className="inline-flex items-center gap-1 font-medium">
      {meta.spin ? <Loader2 size={11} className="animate-spin" /> : meta.icon}
      {meta.label}
    </Badge>
  );
}

const STATUS_META: Record<
  HandoffJob["status"],
  {
    label: string;
    accent: string;
    border: string;
    surface: string;
    spin: boolean;
    icon: React.ReactNode;
  }
> = {
  pending: {
    label: "派发中",
    ...statusCardChrome("muted"),
    spin: true,
    icon: null,
  },
  running: {
    label: "运行中",
    ...statusCardChrome("primary"),
    spin: true,
    icon: null,
  },
  succeeded: {
    label: "已完成",
    ...statusCardChrome("success"),
    spin: false,
    icon: <CheckCircle2 size={11} />,
  },
  failed: {
    label: "失败",
    ...statusCardChrome("destructive"),
    spin: false,
    icon: <AlertTriangle size={11} />,
  },
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`;
}
