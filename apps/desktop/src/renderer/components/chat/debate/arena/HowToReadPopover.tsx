import { MANUAL_HELP, ManualHelpTextLink } from "@/components/ManualHelpLink";
import { Button } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Info } from "lucide-react";
import { type DebateForm, debateFormBlurb } from "../model";
import { SCORE_DIMENSIONS } from "./ScoreBreakdown";

/** 全页唯一概念解释入口（收编质询/结辩/记分/举证等）。 */
export function HowToReadPopover({ form }: { form: DebateForm }) {
  const showScoring = form === "debate";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          className="h-auto px-1.5 py-0.5 text-xs text-muted-foreground"
          icon={<Info size={13} />}
        >
          这场怎么读
        </Button>
      </PopoverTrigger>
      <PopoverContent className="max-w-sm text-sm" align="end">
        <p className="font-medium text-foreground">怎么读这场辩论</p>
        <p className="mt-2 text-muted-foreground">{debateFormBlurb(form)}</p>
        <ul className="mt-3 space-y-2 text-xs text-muted-foreground">
          {showScoring && (
            <>
              <li>
                <span className="font-medium text-foreground">净分</span>
                ：三维分之和减去罚分（可为负）；越高越占优。顶栏比分一眼可读，点净分可看三维构成。
              </li>
              <li>
                <span className="font-medium text-foreground">三维分</span>
                （每轮各维 0–5，中性量；顶栏/战果为跨轮累计）：
                {SCORE_DIMENSIONS.map((d) => (
                  <span key={d.key}>
                    {" "}
                    <span className="text-foreground">{d.label}</span>=
                    {d.description}；
                  </span>
                ))}
              </li>
              <li>
                <span className="font-medium text-foreground">记分口径</span>
                ：每轮收尾由裁判读完该轮立论与质询问答后综合打一次分（不按环节分别计分）；结辩只收束陈词、不计分。
              </li>
              <li>
                <span className="font-medium text-foreground">罚分</span>
                ：谬误、无据硬拗等违规条目；记分牌与裁判札记可展开查看具体犯规。
              </li>
              <li>
                <span className="font-medium text-foreground">动量图</span>
                ：逐轮各方净分柱高；悬停看该轮净分与三维。图例色点对应各方。
              </li>
            </>
          )}
          {!showScoring && form === "red_team" && (
            <li>
              <span className="font-medium text-foreground">Finding 线程</span>
              ：每条刺看刺→回应→复核与状态徽章；终审给门决与 must-fix。
            </li>
          )}
          {!showScoring && form === "roundtable" && (
            <li>
              <span className="font-medium text-foreground">线程与地图</span>
              ：轮内是点名串行对话；终审是按子题组织的共识/分歧地图（含 crux）。
            </li>
          )}
          {showScoring && (
            <>
              <li>
                <span className="font-medium text-foreground">质询</span>
                ：主持人发出必答追问，辩手逐条作答；是否回避由裁判记分与胜负手裁定。
              </li>
              <li>
                <span className="font-medium text-foreground">结辩</span>
                ：各方最后陈词，只讲胜负手。
              </li>
            </>
          )}
          <li>
            <span className="font-medium text-foreground">站队</span>
            ：仅你可见的倾向标记，不影响 AI 裁决。
          </li>
        </ul>
        <p className="mt-3 border-t border-border pt-2">
          <ManualHelpTextLink to={MANUAL_HELP.debate} label="手册·辩论" />
        </p>
      </PopoverContent>
    </Popover>
  );
}
