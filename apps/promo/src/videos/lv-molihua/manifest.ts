import type { ComponentType } from "react";
import {
  StillChapter06,
  StillDecisionBrief,
  StillLogo,
  StillScorePanel,
} from "./KeyStill";
import { ChapterTitleScene } from "./scenes/ChapterTitleScene";
import { LogoScene } from "./scenes/LogoScene";
import {
  CHAPTERS,
  COLD_OPEN,
  FILM_FRAMES,
  FPS,
  HEIGHT,
  LOGO,
  WIDTH,
} from "./timeline";
import {
  ChaptersStandalone,
  ColdOpenStandalone,
  LogoStandalone,
  Video,
} from "./Video";

export interface CompositionDef {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: ComponentType<any>;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  defaultProps?: Record<string, unknown>;
}

export interface StillDefReg {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: ComponentType<any>;
  width: number;
  height: number;
  defaultProps?: Record<string, unknown>;
}

/** Hand-written registration for the LV / 茉莉奶白 hybrid design kit. */
export const lvMolihuaManifest = {
  id: "lv-molihua",
  compositions: [
    {
      id: "LvMolihua",
      component: Video,
      durationInFrames: FILM_FRAMES,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-ColdOpen",
      component: ColdOpenStandalone,
      durationInFrames: COLD_OPEN.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-Chapters",
      component: ChaptersStandalone,
      durationInFrames: CHAPTERS.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-Chapter",
      component: ChapterTitleScene,
      durationInFrames: 60,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
      defaultProps: { chapterIndex: 0 },
    },
    {
      id: "LvMolihua-Logo",
      component: LogoStandalone,
      durationInFrames: LOGO.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
  ] as CompositionDef[],
  stills: [
    {
      id: "LvMolihua-Still-Decision",
      component: StillDecisionBrief,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-Still-Score",
      component: StillScorePanel,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-Still-Chapter06",
      component: StillChapter06,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "LvMolihua-Still-Logo",
      component: StillLogo,
      width: WIDTH,
      height: HEIGHT,
    },
  ] as StillDefReg[],
};
