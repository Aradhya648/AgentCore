import type { ComponentType } from "react";
import { DEMO_LAYOUT } from "../videos/brand-30s/data/layout";
import { STILL_DEFS } from "./data/stills";
import { STILLS_LAYOUT } from "./data/stillsLayout";
import {
  APPSHELL_H,
  APPSHELL_W,
  AppShellStill,
} from "./scenes/AppShellStill";
import {
  MOBILE_H,
  MOBILE_W,
  MobileChatStill,
} from "./scenes/MobileChatStill";
import {
  CLOSEUP_H,
  CLOSEUP_W,
  NodeCloseupStill,
} from "./scenes/NodeCloseupStill";
import { PayoffStill } from "./scenes/PayoffStill";
import { stillFrameSize, stillRatio, StillScene } from "./scenes/StillScene";

export interface StillReg {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: ComponentType<any>;
  width: number;
  height: number;
  defaultProps?: Record<string, unknown>;
}

const payoffSize = stillFrameSize(DEMO_LAYOUT.width, DEMO_LAYOUT.height);

/** Hand-written registration for the stills material package. */
export const stillsManifest = {
  id: "stills",
  stills: [
    {
      id: "Still-appshell",
      component: AppShellStill,
      width: APPSHELL_W,
      height: APPSHELL_H,
    },
    {
      id: "Still-nodecard",
      component: NodeCloseupStill,
      width: CLOSEUP_W,
      height: CLOSEUP_H,
    },
    {
      id: "Still-payoff",
      component: PayoffStill,
      width: payoffSize.width,
      height: payoffSize.height,
    },
    {
      id: "Still-mobile",
      component: MobileChatStill,
      width: MOBILE_W,
      height: MOBILE_H,
    },
    ...STILL_DEFS.map((def) => {
      const lay = STILLS_LAYOUT[def.id];
      const { width, height } = stillFrameSize(
        lay.width,
        lay.height,
        stillRatio(def),
      );
      return {
        id: `Still-${def.id}`,
        component: StillScene,
        width,
        height,
        defaultProps: { scenarioId: def.id },
      };
    }),
  ] as StillReg[],
};
