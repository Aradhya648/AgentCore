"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Stars } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import * as THREE from "three";
import Constellation from "./Constellation";
import { buildPalette } from "./palette";
import { CAMERA_KEYS, cameraAt, progressStore } from "./timeline";

/**
 * 方案 C「3D 沉浸宇宙」的渲染层：固定全屏 Canvas，
 * 相机沿 timeline.ts 的关键帧旅程随滚动推进，Bloom 提供星体辉光。
 * 颜色全部来自品牌语义 token（palette.ts 解析），无硬编码色值。
 */

function CameraRig() {
  const camera = useThree((s) => s.camera);
  const lookTarget = useRef(new THREE.Vector3(...CAMERA_KEYS[0].look));
  const tmpPos = useRef(new THREE.Vector3());
  const tmpLook = useRef(new THREE.Vector3());

  useFrame((state, rawDt) => {
    const dt = Math.min(rawDt, 0.1);
    const { pos, look } = cameraAt(progressStore.value);
    tmpPos.current.set(pos[0], pos[1], pos[2]);
    tmpLook.current.set(look[0], look[1], look[2]);

    // 鼠标视差（滚动进度不受影响，纯装饰）
    if (!progressStore.reducedMotion && !progressStore.snap) {
      tmpPos.current.x += state.pointer.x * 0.55;
      tmpPos.current.y += state.pointer.y * 0.35;
    }

    if (progressStore.snap || progressStore.reducedMotion) {
      camera.position.copy(tmpPos.current);
      lookTarget.current.copy(tmpLook.current);
    } else {
      const k = 1 - Math.exp(-dt * 3.2);
      camera.position.lerp(tmpPos.current, k);
      lookTarget.current.lerp(tmpLook.current, k);
    }
    camera.lookAt(lookTarget.current);
  });

  return null;
}

function SceneContent() {
  const pal = useMemo(() => buildPalette(), []);
  const { scene } = useThree();

  useMemo(() => {
    scene.background = pal.background.clone();
    scene.fog = new THREE.Fog(pal.background.clone(), 26, 78);
  }, [scene, pal]);

  return (
    <>
      <CameraRig />
      <Stars
        radius={46}
        depth={32}
        count={3400}
        factor={5.2}
        saturation={0}
        fade
        speed={progressStore.reducedMotion ? 0 : 0.9}
      />
      <Constellation pal={pal} />
      <EffectComposer multisampling={0}>
        <Bloom
          mipmapBlur
          intensity={1.15}
          luminanceThreshold={0.22}
          luminanceSmoothing={0.32}
          radius={0.78}
        />
      </EffectComposer>
    </>
  );
}

export default function Scene3D() {
  return (
    <Canvas
      dpr={[1, 1.75]}
      gl={{
        antialias: true,
        alpha: false,
        powerPreference: "high-performance",
      }}
      camera={{
        fov: 50,
        near: 0.1,
        far: 140,
        position: CAMERA_KEYS[0].pos,
      }}
      style={{ position: "absolute", inset: 0 }}
    >
      <SceneContent />
    </Canvas>
  );
}
