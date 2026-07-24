import type { ComponentType } from "react";
import { PixelCheck } from "./PixelCheck";
import { LogoScene } from "./scenes/LogoScene";
import {
  FPS,
  HEIGHT,
  LOGO,
  OPENING,
  PROMO_FRAMES,
  RUN,
  SCENARIOS,
  WIDTH,
} from "./timeline";
import {
  OpeningStandalone,
  RunStandalone,
  ScenarioStandalone,
  Video,
} from "./Video";

export interface CompositionDef {
  id: string;
  // Remotion compositions accept package-specific props via defaultProps / input props.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: ComponentType<any>;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
}

export interface StillDefReg {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: ComponentType<any>;
  width: number;
  height: number;
  defaultProps?: Record<string, unknown>;
}

/** Hand-written registration for the brand-30s film + Studio scene comps. */
export const brand30sManifest = {
  id: "brand-30s",
  compositions: [
    {
      id: "Promo",
      component: Video,
      durationInFrames: PROMO_FRAMES,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "Opening",
      component: OpeningStandalone,
      durationInFrames: OPENING.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "Run",
      component: RunStandalone,
      durationInFrames: RUN.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "Scenarios",
      component: ScenarioStandalone,
      durationInFrames: SCENARIOS.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
    {
      id: "Logo",
      component: LogoScene,
      durationInFrames: LOGO.frames,
      fps: FPS,
      width: WIDTH,
      height: HEIGHT,
    },
  ] as CompositionDef[],
  stills: [
    {
      id: "PixelCheck",
      component: PixelCheck,
      width: WIDTH,
      height: HEIGHT,
    },
  ] as StillDefReg[],
};
