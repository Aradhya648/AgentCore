import "./core/styles.css";
import { Composition, Still } from "remotion";
import { ensurePromoFonts } from "./core/fonts";
import { stillsManifest } from "./stills/manifest";
import { brand30sManifest } from "./videos/brand-30s/manifest";
import { lvMolihuaManifest } from "./videos/lv-molihua/manifest";

// Kick off webfont loading at module eval (registers a delayRender) so every
// composition waits for Inter + Noto Sans SC before its first frame.
ensurePromoFonts();

/**
 * Remotion root — hand-written registry of video + still packages.
 * Add a new video: create src/videos/<id>/ with manifest.ts, then import + spread here.
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      {brand30sManifest.compositions.map((c) => (
        <Composition
          key={c.id}
          id={c.id}
          component={c.component}
          durationInFrames={c.durationInFrames}
          fps={c.fps}
          width={c.width}
          height={c.height}
        />
      ))}

      {brand30sManifest.stills.map((s) => (
        <Still
          key={s.id}
          id={s.id}
          component={s.component}
          width={s.width}
          height={s.height}
          defaultProps={s.defaultProps}
        />
      ))}

      {lvMolihuaManifest.compositions.map((c) => (
        <Composition
          key={c.id}
          id={c.id}
          component={c.component}
          durationInFrames={c.durationInFrames}
          fps={c.fps}
          width={c.width}
          height={c.height}
          defaultProps={c.defaultProps}
        />
      ))}

      {lvMolihuaManifest.stills.map((s) => (
        <Still
          key={s.id}
          id={s.id}
          component={s.component}
          width={s.width}
          height={s.height}
          defaultProps={s.defaultProps}
        />
      ))}

      {stillsManifest.stills.map((s) => (
        <Still
          key={s.id}
          id={s.id}
          component={s.component}
          width={s.width}
          height={s.height}
          defaultProps={s.defaultProps}
        />
      ))}
    </>
  );
};
