/** Layout one or more turn DAGs (ELK) for the conversation canvas. */

import {
  type GroupLayout,
  HEIGHT_RELAYOUT_DEBOUNCE_MS,
  type NodeSizeMap,
  buildNodeSizeMap,
  computeLayout,
  measuredHeightsMatchSizes,
  nodeSpacingForFitMode,
} from "@/lib/elk-layout";
import type { ElkGraphLayout } from "@/lib/graph-layout-utils";
import { computeLayoutHints } from "@/lib/layoutHints";
import {
  isGraphTraceEnabled,
  traceGraphHeightRelayout,
  traceGraphLayoutOk,
  traceGraphStructure,
} from "@/services/graphTrace";
import type { Execution } from "@/stores/execution";
import type { GraphEdge, GraphLayout } from "@/stores/graph";
import type { NodeChange } from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ActCardLayout,
  computeActLodLayout,
  defaultFocusedActId,
} from "./actLod";
import { INPUT_ID } from "./constants";
import {
  type GraphFoldInfo,
  type SubTeam,
  buildGraphStructure,
  computeGraphFold,
} from "./helpers";
import { logLayoutFailure } from "./layoutFailure";
import { type GraphScene, buildGraphScene } from "./scene";
import type { GraphFitMode } from "./useGraphViewport";

/** ≥2 acts → the graph renders as a 幕级 LOD chain (批 R2) instead of one flat DAG. */
function isMultiActExecution(execution: Execution | null): boolean {
  return (execution?.acts?.length ?? 0) >= 2;
}

export interface TurnLayoutSlice {
  positions: Record<string, { x: number; y: number }>;
  edges: GraphEdge[];
  bbox: { width: number; height: number } | null;
  layoutReady: boolean;
  /** ELK 失败时非空；与 layoutReady=false 同时出现，避免永久空白占位。 */
  layoutError: string | null;
  nodeHeights: Record<string, number>;
  nodeSizes: Record<string, { width: number; height: number }>;
  groups: GroupLayout[];
  subTeams: SubTeam[];
  foldInfo: GraphFoldInfo | null;
  /** Structural IR for this turn (fold / attribution / bands). */
  scene: GraphScene | null;
  /** 幕级 LOD（批 R2）：多幕回合的折叠幕摘要卡；单幕恒 []。 */
  actCards: ActCardLayout[];
}

const EMPTY_SLICE: TurnLayoutSlice = {
  positions: {},
  edges: [],
  bbox: null,
  layoutReady: false,
  layoutError: null,
  nodeHeights: {},
  nodeSizes: {},
  groups: [],
  subTeams: [],
  foldInfo: null,
  scene: null,
  actCards: [],
};

const EMPTY_SUBTEAMS: SubTeam[] = [];

function sizeMapForNodes(
  nodeIds: string[],
  measuredHeights?: Readonly<Record<string, number>>,
): NodeSizeMap {
  const out = buildNodeSizeMap(nodeIds, measuredHeights);
  // Bookends keep a slot even if structure omitted them from nodeIds.
  if (!out[INPUT_ID]) {
    out[INPUT_ID] = buildNodeSizeMap([INPUT_ID], measuredHeights)[INPUT_ID];
  }
  return out;
}

function expandedUnitsFromFold(
  runs: Execution["runs"],
  collapsedSubtrees: ReadonlySet<string>,
): Set<string> {
  const captainId = runs.find((r) => r.kind === "captain")?.id ?? null;
  const foldInfo = computeGraphFold(runs, captainId);
  const expanded = new Set<string>();
  for (const unit of foldInfo.descendants.keys()) {
    if (foldInfo.debateUnits.has(unit)) continue;
    if (!collapsedSubtrees.has(unit)) expanded.add(unit);
  }
  return expanded;
}

function applyDimensionChanges(
  prev: Record<string, number>,
  changes: NodeChange[],
): Record<string, number> | null {
  let next = prev;
  for (const c of changes) {
    if (c.type === "dimensions" && c.dimensions) {
      const h = c.dimensions.height;
      if (h > 0 && prev[c.id] !== h) {
        if (next === prev) next = { ...prev };
        next[c.id] = h;
      }
    }
  }
  return next === prev ? null : next;
}

export function useGraphLayout(
  execution: Execution | null,
  layoutKind: GraphLayout,
  fitMode: GraphFitMode = "view",
  expandedUnits: ReadonlySet<string> = new Set(),
  focusedActId: string | null = null,
): TurnLayoutSlice & {
  onNodesChange: (changes: NodeChange[]) => void;
} {
  const projectedRunsRef = useRef(execution?.runs);
  projectedRunsRef.current = execution?.runs;
  const executionRef = useRef(execution);
  executionRef.current = execution;

  const [positions, setPositions] = useState<
    Record<string, { x: number; y: number }>
  >({});
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [bbox, setBbox] = useState<{ width: number; height: number } | null>(
    null,
  );
  const [nodeSizes, setNodeSizes] = useState<
    Record<string, { width: number; height: number }>
  >({});
  const [layoutReady, setLayoutReady] = useState(false);
  const [layoutError, setLayoutError] = useState<string | null>(null);
  const [nodeHeights, setNodeHeights] = useState<Record<string, number>>({});
  const [groups, setGroups] = useState<GroupLayout[]>([]);
  const [actCards, setActCards] = useState<ActCardLayout[]>([]);

  const nodeHeightsRef = useRef(nodeHeights);
  nodeHeightsRef.current = nodeHeights;
  const nodeSizesRef = useRef(nodeSizes);
  nodeSizesRef.current = nodeSizes;
  const positionsRef = useRef(positions);
  positionsRef.current = positions;

  const setLayout = useCallback(
    (
      nextPositions: Record<string, { x: number; y: number }>,
      nextEdges: GraphEdge[],
    ) => {
      setPositions(nextPositions);
      setEdges(nextEdges);
    },
    [],
  );

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodeHeights((prev) => applyDimensionChanges(prev, changes) ?? prev);
  }, []);

  const structuralKey = useMemo(() => {
    if (!execution) return "";
    const struct = graphStructureKey(execution.runs);
    const expandKey = [...expandedUnits].sort().join(",");
    // 幕级 LOD：幕序列 + 聚焦幕进 key，切幕/换焦点触发聚焦幕重排（内容更新不触发）。
    const actsKey = execution.acts?.map((a) => a.actId).join(",") ?? "";
    return `${struct}::${expandKey}::acts=${actsKey}::focus=${focusedActId ?? ""}`;
  }, [execution, expandedUnits, focusedActId]);

  // Single structural IR for projection + bands. Rebuilt on structure / expand
  // change (execution identity captures late-bound continuation / act fields the
  // structural key does not, matching the prior subTeams/foldInfo memos).
  const scene = useMemo<GraphScene | null>(() => {
    if (!execution) return null;
    return buildGraphScene(execution, { inputId: INPUT_ID, expandedUnits });
  }, [execution, expandedUnits]);
  const sceneRef = useRef(scene);
  sceneRef.current = scene;
  const subTeams = scene?.subTeams ?? EMPTY_SUBTEAMS;
  const foldInfo = scene?.fold ?? null;

  // 结构重算：保留上一帧 layoutReady/positions，勿置 false（否则 GraphView 会卸载
  // 整棵 ReactFlow → 追加委派时整图闪烁）。首帧或清空仍走 layoutReady=false。
  const hasShownLayoutRef = useRef(false);
  const layoutGenRef = useRef(0);

  // expandedUnits + focusedActId 已编入 structuralKey；勿再依赖其引用（调用方偶发 new Set() 会死循环）。
  // biome-ignore lint/correctness/useExhaustiveDependencies: structuralKey encodes expandedUnits + focusedActId
  useEffect(() => {
    if (!structuralKey) {
      hasShownLayoutRef.current = false;
      if (isGraphTraceEnabled()) {
        traceGraphStructure({ cleared: true });
      }
      setLayout({}, []);
      setBbox(null);
      setNodeSizes({});
      setGroups([]);
      setActCards([]);
      setLayoutReady(false);
      setLayoutError(null);
      return;
    }

    const gen = ++layoutGenRef.current;
    let cancelled = false;
    // 仅首帧 blank；已有成图时保持 ReactFlow 挂载，等 ELK 就绪后换坐标。
    if (!hasShownLayoutRef.current) {
      setLayoutReady(false);
    }
    setLayoutError(null);
    if (isGraphTraceEnabled()) {
      const prevPosIds = Object.keys(positionsRef.current);
      traceGraphStructure({
        gen,
        structuralKey: structuralKey.slice(0, 120),
        keepOldLayout: hasShownLayoutRef.current,
        prevPosCount: prevPosIds.length,
        prevPosIds,
      });
    }

    const onOk = (
      nextPositions: Record<string, { x: number; y: number }>,
      nextEdges: GraphEdge[],
      width: number,
      height: number,
      sizeMap: NodeSizeMap,
      nextGroups: GroupLayout[],
      cards: ActCardLayout[],
    ) => {
      if (cancelled || gen !== layoutGenRef.current) return;
      hasShownLayoutRef.current = true;
      if (isGraphTraceEnabled()) {
        const sceneIds =
          sceneRef.current?.nodeIds.slice() ?? Object.keys(nextPositions);
        traceGraphLayoutOk({
          phase: "structure",
          gen,
          posIds: Object.keys(nextPositions),
          sceneIds,
          bbox: { width, height },
        });
      }
      setLayout(nextPositions, nextEdges);
      setBbox({ width, height });
      setNodeSizes(sizeMap);
      setGroups(nextGroups);
      setActCards(cards);
      setLayoutError(null);
      setLayoutReady(true);
    };
    const onErr = (err: unknown) => {
      if (cancelled || gen !== layoutGenRef.current) return;
      const message = logLayoutFailure(err, { fitMode, layoutKind });
      // 重算失败：保留旧图（已日志）；首帧失败才 blank + 错误面。
      if (!hasShownLayoutRef.current) {
        setLayout({}, []);
        setBbox(null);
        setNodeSizes({});
        setGroups([]);
        setActCards([]);
        setLayoutReady(false);
        setLayoutError(message);
      }
    };

    const exec = executionRef.current;
    const knownHeights = nodeHeightsRef.current;
    // 幕级 LOD（≥2 幕）：只为聚焦幕算完整布局 + 幕摘要卡链（画布 per-turn 范式）。
    if (exec && isMultiActExecution(exec)) {
      const sceneNow =
        sceneRef.current ??
        buildGraphScene(exec, { inputId: INPUT_ID, expandedUnits });
      computeActLodLayout(
        exec,
        sceneNow,
        focusedActId,
        layoutKind,
        fitMode,
        knownHeights,
      )
        .then((res) =>
          onOk(
            res.positions,
            res.edges,
            res.bbox.width,
            res.bbox.height,
            res.nodeSizes,
            res.groups,
            res.cards,
          ),
        )
        .catch(onErr);
      return () => {
        cancelled = true;
      };
    }

    // 单幕：既有整图 ELK 路径，像素级零变化（冷启动）；已知实测高一并灌入。
    const runs = projectedRunsRef.current ?? [];
    const captainId = runs.find((r) => r.kind === "captain")?.id ?? null;
    const {
      nodeIds,
      rawEdges,
      subTeams: layoutSubTeams,
    } = buildGraphStructure(runs, INPUT_ID, expandedUnits);
    const hints = computeLayoutHints(layoutSubTeams, rawEdges);
    const sizeMap = sizeMapForNodes(nodeIds, knownHeights);
    const elkLayout = layoutKind as ElkGraphLayout;
    const nodeSpacing = nodeSpacingForFitMode(fitMode);
    computeLayout(
      nodeIds,
      rawEdges,
      elkLayout,
      {
        source: INPUT_ID,
        sink: captainId ?? undefined,
      },
      layoutSubTeams,
      nodeSpacing,
      sizeMap,
      hints,
    )
      .then((result) =>
        onOk(
          result.positions,
          rawEdges,
          result.width,
          result.height,
          sizeMap,
          result.groups,
          [],
        ),
      )
      .catch(onErr);
    return () => {
      cancelled = true;
    };
  }, [structuralKey, layoutKind, fitMode, setLayout]);

  // 实测高度回灌：防抖二次 ELK（结构不变时只跟高度走，接受轻微位置跳动）。
  // biome-ignore lint/correctness/useExhaustiveDependencies: height-driven; structuralKey/layoutKind/fitMode gate identity
  useEffect(() => {
    if (!structuralKey || !layoutReady) return;
    const exec = executionRef.current;
    if (!exec) return;

    const heights = nodeHeights;
    const currentSizes = nodeSizesRef.current;
    const sizeIds = Object.keys(currentSizes);
    if (sizeIds.length === 0) return;
    if (measuredHeightsMatchSizes(sizeIds, currentSizes, heights)) return;

    let cancelled = false;
    const gen = layoutGenRef.current;
    const timer = setTimeout(() => {
      if (cancelled || gen !== layoutGenRef.current) return;

      if (isGraphTraceEnabled()) {
        traceGraphHeightRelayout({
          gen,
          measuredIds: Object.keys(heights),
          sizeIds: sizeIds.slice(),
        });
      }

      const onOk = (
        nextPositions: Record<string, { x: number; y: number }>,
        nextEdges: GraphEdge[],
        width: number,
        height: number,
        sizeMap: NodeSizeMap,
        nextGroups: GroupLayout[],
        cards: ActCardLayout[],
      ) => {
        if (cancelled || gen !== layoutGenRef.current) return;
        if (isGraphTraceEnabled()) {
          const sceneIds =
            sceneRef.current?.nodeIds.slice() ?? Object.keys(nextPositions);
          traceGraphLayoutOk({
            phase: "height-relayout",
            gen,
            posIds: Object.keys(nextPositions),
            sceneIds,
            bbox: { width, height },
          });
        }
        setLayout(nextPositions, nextEdges);
        setBbox({ width, height });
        setNodeSizes(sizeMap);
        setGroups(nextGroups);
        setActCards(cards);
      };
      const onErr = (err: unknown) => {
        if (cancelled || gen !== layoutGenRef.current) return;
        logLayoutFailure(err, {
          fitMode,
          layoutKind,
          phase: "height-relayout",
        });
      };

      if (isMultiActExecution(exec)) {
        const sceneNow =
          sceneRef.current ??
          buildGraphScene(exec, { inputId: INPUT_ID, expandedUnits });
        computeActLodLayout(
          exec,
          sceneNow,
          focusedActId,
          layoutKind,
          fitMode,
          heights,
        )
          .then((res) =>
            onOk(
              res.positions,
              res.edges,
              res.bbox.width,
              res.bbox.height,
              res.nodeSizes,
              res.groups,
              res.cards,
            ),
          )
          .catch(onErr);
        return;
      }

      const runs = projectedRunsRef.current ?? [];
      const captainId = runs.find((r) => r.kind === "captain")?.id ?? null;
      const {
        nodeIds,
        rawEdges,
        subTeams: layoutSubTeams,
      } = buildGraphStructure(runs, INPUT_ID, expandedUnits);
      const hints = computeLayoutHints(layoutSubTeams, rawEdges);
      const sizeMap = sizeMapForNodes(nodeIds, heights);
      computeLayout(
        nodeIds,
        rawEdges,
        layoutKind as ElkGraphLayout,
        { source: INPUT_ID, sink: captainId ?? undefined },
        layoutSubTeams,
        nodeSpacingForFitMode(fitMode),
        sizeMap,
        hints,
      )
        .then((result) =>
          onOk(
            result.positions,
            rawEdges,
            result.width,
            result.height,
            sizeMap,
            result.groups,
            [],
          ),
        )
        .catch(onErr);
    }, HEIGHT_RELAYOUT_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [nodeHeights, layoutReady, structuralKey, layoutKind, fitMode, setLayout]);

  return {
    positions,
    edges,
    bbox,
    layoutReady,
    layoutError,
    nodeHeights,
    nodeSizes,
    onNodesChange,
    groups,
    subTeams,
    foldInfo,
    scene,
    actCards,
  };
}

export interface MultiTurnLayoutInput {
  turnId: string;
  execution: Execution;
}

/**
 * Layout every expanded team turn. Hook count is fixed; turn set is keyed.
 */
const EMPTY_ACT_FOCUS: ReadonlyMap<string, string | null | undefined> =
  new Map();

export function useMultiTurnLayouts(
  turns: MultiTurnLayoutInput[],
  layoutKind: GraphLayout,
  collapsedSubtrees: ReadonlySet<string>,
  fitMode: GraphFitMode = "contain",
  actFocusChoices: ReadonlyMap<
    string,
    string | null | undefined
  > = EMPTY_ACT_FOCUS,
): {
  layouts: Record<string, TurnLayoutSlice>;
  onNodesChange: (turnId: string, changes: NodeChange[]) => void;
} {
  const [layouts, setLayouts] = useState<Record<string, TurnLayoutSlice>>({});
  const [heightByTurn, setHeightByTurn] = useState<
    Record<string, Record<string, number>>
  >({});
  const genRef = useRef(0);
  const turnsRef = useRef(turns);
  turnsRef.current = turns;
  const layoutsRef = useRef(layouts);
  layoutsRef.current = layouts;
  const heightByTurnRef = useRef(heightByTurn);
  heightByTurnRef.current = heightByTurn;
  const collapsedRef = useRef(collapsedSubtrees);
  collapsedRef.current = collapsedSubtrees;
  const actFocusRef = useRef(actFocusChoices);
  actFocusRef.current = actFocusChoices;

  const turnKey = useMemo(
    () =>
      turns
        .map((t) => {
          const expanded = expandedUnitsFromFold(
            t.execution.runs,
            collapsedSubtrees,
          );
          const units = [...expanded].sort().join(",");
          const struct = graphStructureKey(t.execution.runs);
          // 幕级 LOD：多幕回合把幕序列 + 有效聚焦幕（含活跃幕自动跟随）编入 key，
          // 使切幕 / 活跃幕推进触发聚焦幕重排（单幕回合此段恒空 → key 不变）。
          let actKey = "";
          if (isMultiActExecution(t.execution)) {
            const scene = buildGraphScene(t.execution, {
              inputId: INPUT_ID,
              expandedUnits: expanded,
            });
            const focus = defaultFocusedActId(
              scene,
              t.execution.status,
              actFocusChoices.get(t.turnId),
            );
            actKey = `#acts=${t.execution.acts.map((a) => a.actId).join(",")}#focus=${focus ?? "none"}`;
          }
          return `${t.turnId}#${struct}#${units}${actKey}`;
        })
        .join("||"),
    [turns, collapsedSubtrees, actFocusChoices],
  );

  // turnKey encodes turns + collapsedSubtrees; height patches debounce into a
  // separate secondary ELK (below) so streaming measure does not tear structure.
  // biome-ignore lint/correctness/useExhaustiveDependencies: structural key is turnKey; height patches intentionally omitted
  useEffect(() => {
    const gen = ++genRef.current;
    if (turns.length === 0) {
      setLayouts({});
      return;
    }

    let cancelled = false;
    const next: Record<string, TurnLayoutSlice> = {};

    const run = async () => {
      for (const t of turns) {
        const expandedUnits = expandedUnitsFromFold(
          t.execution.runs,
          collapsedSubtrees,
        );
        const captainId =
          t.execution.runs.find((r) => r.kind === "captain")?.id ?? null;
        const scene = buildGraphScene(t.execution, {
          inputId: INPUT_ID,
          expandedUnits,
        });
        const knownHeights = heightByTurnRef.current[t.turnId] ?? {};

        // 幕级 LOD（≥2 幕）：只为聚焦幕算完整布局 + 幕摘要卡链，与内联/全屏同语义。
        if (isMultiActExecution(t.execution)) {
          const focus = defaultFocusedActId(
            scene,
            t.execution.status,
            actFocusChoices.get(t.turnId),
          );
          try {
            const res = await computeActLodLayout(
              t.execution,
              scene,
              focus,
              layoutKind,
              fitMode,
              knownHeights,
            );
            if (cancelled || gen !== genRef.current) return;
            next[t.turnId] = {
              positions: res.positions,
              edges: res.edges,
              bbox: res.bbox,
              layoutReady: true,
              layoutError: null,
              nodeHeights: knownHeights,
              nodeSizes: res.nodeSizes,
              groups: res.groups,
              subTeams: scene.subTeams,
              foldInfo: scene.fold,
              scene,
              actCards: res.cards,
            };
          } catch (err) {
            if (cancelled || gen !== genRef.current) return;
            const message = logLayoutFailure(err, {
              fitMode,
              layoutKind,
              turnId: t.turnId,
            });
            next[t.turnId] = {
              ...EMPTY_SLICE,
              layoutError: message,
              foldInfo: scene.fold,
              scene,
            };
          }
          continue;
        }

        const { nodeIds, edges: rawEdges, subTeams, fold: foldInfo } = scene;
        const sizeMap = sizeMapForNodes(nodeIds, knownHeights);

        try {
          const result = await computeLayout(
            nodeIds,
            rawEdges,
            layoutKind as ElkGraphLayout,
            { source: INPUT_ID, sink: captainId ?? undefined },
            subTeams,
            nodeSpacingForFitMode(fitMode),
            sizeMap,
            scene.layoutHints,
          );
          if (cancelled || gen !== genRef.current) return;
          next[t.turnId] = {
            positions: result.positions,
            edges: rawEdges,
            bbox: { width: result.width, height: result.height },
            layoutReady: true,
            layoutError: null,
            nodeHeights: knownHeights,
            nodeSizes: sizeMap,
            groups: result.groups,
            subTeams,
            foldInfo,
            scene,
            actCards: [],
          };
        } catch (err) {
          if (cancelled || gen !== genRef.current) return;
          const message = logLayoutFailure(err, {
            fitMode,
            layoutKind,
            turnId: t.turnId,
          });
          next[t.turnId] = {
            ...EMPTY_SLICE,
            layoutError: message,
            foldInfo: scene.fold,
            scene,
          };
        }
      }
      if (cancelled || gen !== genRef.current) return;
      setLayouts(next);
    };

    // Mark not-ready stubs so spine doesn't flash wrong LOD.
    const stubs: Record<string, TurnLayoutSlice> = {};
    for (const t of turns) {
      const stubScene = buildGraphScene(t.execution, {
        inputId: INPUT_ID,
        expandedUnits: expandedUnitsFromFold(
          t.execution.runs,
          collapsedSubtrees,
        ),
      });
      stubs[t.turnId] = {
        ...EMPTY_SLICE,
        foldInfo: stubScene.fold,
        scene: stubScene,
        layoutReady: false,
      };
    }
    setLayouts((prev) => {
      const merged = { ...stubs };
      for (const id of Object.keys(stubs)) {
        if (prev[id]?.layoutReady) merged[id] = prev[id];
      }
      return merged;
    });

    void run();
    return () => {
      cancelled = true;
    };
  }, [turnKey, layoutKind, fitMode]);

  // Per-turn measured-height secondary ELK (debounced).
  // biome-ignore lint/correctness/useExhaustiveDependencies: heightByTurn drives; turnKey/layoutKind/fitMode gate identity
  useEffect(() => {
    const pending = Object.entries(heightByTurn).filter(([turnId, heights]) => {
      const slice = layoutsRef.current[turnId];
      if (!slice?.layoutReady) return false;
      const ids = Object.keys(slice.nodeSizes);
      if (ids.length === 0) return false;
      return !measuredHeightsMatchSizes(ids, slice.nodeSizes, heights);
    });
    if (pending.length === 0) return;

    let cancelled = false;
    const gen = genRef.current;
    const timer = setTimeout(() => {
      if (cancelled || gen !== genRef.current) return;
      void (async () => {
        for (const [turnId] of pending) {
          if (cancelled || gen !== genRef.current) return;
          const t = turnsRef.current.find((x) => x.turnId === turnId);
          if (!t) continue;
          const heights = heightByTurnRef.current[turnId] ?? {};
          const expandedUnits = expandedUnitsFromFold(
            t.execution.runs,
            collapsedRef.current,
          );
          const scene = buildGraphScene(t.execution, {
            inputId: INPUT_ID,
            expandedUnits,
          });
          try {
            if (isMultiActExecution(t.execution)) {
              const focus = defaultFocusedActId(
                scene,
                t.execution.status,
                actFocusRef.current.get(t.turnId),
              );
              const res = await computeActLodLayout(
                t.execution,
                scene,
                focus,
                layoutKind,
                fitMode,
                heights,
              );
              if (cancelled || gen !== genRef.current) return;
              setLayouts((prev) => ({
                ...prev,
                [turnId]: {
                  positions: res.positions,
                  edges: res.edges,
                  bbox: res.bbox,
                  layoutReady: true,
                  layoutError: null,
                  nodeHeights: heights,
                  nodeSizes: res.nodeSizes,
                  groups: res.groups,
                  subTeams: scene.subTeams,
                  foldInfo: scene.fold,
                  scene,
                  actCards: res.cards,
                },
              }));
              continue;
            }

            const captainId =
              t.execution.runs.find((r) => r.kind === "captain")?.id ?? null;
            const {
              nodeIds,
              edges: rawEdges,
              subTeams,
              fold: foldInfo,
            } = scene;
            const sizeMap = sizeMapForNodes(nodeIds, heights);
            const result = await computeLayout(
              nodeIds,
              rawEdges,
              layoutKind as ElkGraphLayout,
              { source: INPUT_ID, sink: captainId ?? undefined },
              subTeams,
              nodeSpacingForFitMode(fitMode),
              sizeMap,
              scene.layoutHints,
            );
            if (cancelled || gen !== genRef.current) return;
            setLayouts((prev) => ({
              ...prev,
              [turnId]: {
                positions: result.positions,
                edges: rawEdges,
                bbox: { width: result.width, height: result.height },
                layoutReady: true,
                layoutError: null,
                nodeHeights: heights,
                nodeSizes: sizeMap,
                groups: result.groups,
                subTeams,
                foldInfo,
                scene,
                actCards: [],
              },
            }));
          } catch (err) {
            if (cancelled || gen !== genRef.current) return;
            logLayoutFailure(err, {
              fitMode,
              layoutKind,
              turnId,
              phase: "height-relayout",
            });
          }
        }
      })();
    }, HEIGHT_RELAYOUT_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [heightByTurn, turnKey, layoutKind, fitMode]);

  const onNodesChange = useCallback((turnId: string, changes: NodeChange[]) => {
    setHeightByTurn((prev) => {
      const cur = prev[turnId] ?? {};
      const next = applyDimensionChanges(cur, changes);
      if (!next) return prev;
      return { ...prev, [turnId]: next };
    });
    setLayouts((prev) => {
      const slice = prev[turnId];
      if (!slice) return prev;
      const next = applyDimensionChanges(slice.nodeHeights, changes);
      if (!next) return prev;
      return {
        ...prev,
        [turnId]: { ...slice, nodeHeights: next },
      };
    });
  }, []);

  return { layouts, onNodesChange };
}

/**
 * Structural fingerprint for ELK re-layout. Content/streaming fields are
 * intentionally excluded so delta floods do not tear down the graph.
 */
export function graphStructureKey(
  runs: ReadonlyArray<{
    id: string;
    dependsOn: readonly string[];
    parentRunId?: string | null;
    replacesRunId?: string | null;
  }>,
): string {
  return runs
    .map(
      (s) =>
        `${s.id}:${s.dependsOn.join(",")}:${s.parentRunId ?? ""}:${s.replacesRunId ?? ""}`,
    )
    .join("|");
}

export { expandedUnitsFromFold, sizeMapForNodes as buildNodeSizeMap };
