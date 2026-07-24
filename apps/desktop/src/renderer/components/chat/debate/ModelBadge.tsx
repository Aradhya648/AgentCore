import { Cpu } from "lucide-react";
import { modelVendorLabel } from "./model";

/**
 * 「由哪个模型驱动」徽章（真·多模型辩论）—— 把一方的 `model`（`provider/model`）映射成友好厂商名
 * （豆包 / DeepSeek / …，见 {@link modelVendorLabel}），让用户一眼看出每一方背后是哪个大模型：
 * 「谁更聪明」对战的核心可读性。空 model（平台默认 / 进行中 roster 未到）→ 不渲染。
 *
 * **模型 ≠ 状态 ≠ 身份**：身份色标在名字 pill（`agentColorVar`）、状态走状态点，模型是另一维元
 * 数据，故走中性 `muted` 样式（遵 color-tokens，不与状态/身份色竞争）。`title` 给出完整模型 id。
 */
export function ModelBadge({ model }: { model: string | null | undefined }) {
  const label = modelVendorLabel(model);
  if (!label) return null;
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground"
      title={model ? `由 ${label} 驱动（${model}）` : undefined}
    >
      <Cpu size={11} aria-hidden />
      {label}
    </span>
  );
}
