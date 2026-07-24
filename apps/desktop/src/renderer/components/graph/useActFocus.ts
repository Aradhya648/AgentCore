/**
 * 幕级 LOD 聚焦态（批 R2）——UI 态，不持久化到服务端。
 *
 * 默认：执行中自动聚焦活跃幕（{@link GraphScene.activeActId}）；完成态整链折叠为一行
 * 幕摘要卡。用户点某幕卡 → 聚焦该幕（唯一聚焦幕）；`collapseActs` 折回整链卡。用户
 * 一旦选择即锁定（含主动折叠），不再被进行中自动聚焦覆盖。单幕回合不消费此 hook。
 */

import type { ExecutionStatus } from "@/stores/execution";
import { useCallback, useMemo, useState } from "react";
import { defaultFocusedActId } from "./actLod";
import type { GraphScene } from "./scene";

export interface ActFocus {
  focusedActId: string | null;
  focusAct: (actId: string) => void;
  collapseActs: () => void;
}

export function useActFocus(
  scene: GraphScene | null,
  status: ExecutionStatus | undefined,
): ActFocus {
  // undefined = no user choice yet (follow the live default).
  const [userChoice, setUserChoice] = useState<string | null | undefined>(
    undefined,
  );

  const focusedActId = useMemo(() => {
    if (!scene) return null;
    return defaultFocusedActId(scene, status, userChoice);
  }, [scene, status, userChoice]);

  const focusAct = useCallback((actId: string) => setUserChoice(actId), []);
  const collapseActs = useCallback(() => setUserChoice(null), []);

  return { focusedActId, focusAct, collapseActs };
}
