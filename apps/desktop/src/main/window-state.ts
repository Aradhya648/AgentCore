import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { type BrowserWindow, type Rectangle, app, screen } from "electron";

/**
 * 主窗口尺寸/位置/最大化状态的持久化（前端技术与架构.md §7.2 主进程架构）。
 *
 * 桌面端的基本期待：重启后窗口回到上次的大小与位置，而非每次都跳回固定默认。
 * 状态以小 JSON 落 `userData/window-state.json`，与 `fs-service` 的 `fs-roots.json`
 * 同源约定（小配置直接读写用户数据目录，不引第三方 store）。
 */

const DEFAULTS = { width: 1400, height: 900 } as const;

export interface WindowState {
  width: number;
  height: number;
  x?: number;
  y?: number;
  isMaximized?: boolean;
}

function stateFilePath(): string {
  return join(app.getPath("userData"), "window-state.json");
}

/**
 * 矩形是否与某块显示器的工作区相交。用于丢弃「在已拔掉的副屏上保存」的坐标，
 * 避免窗口在重启后开到看不见的屏外。
 */
function isVisibleOnSomeDisplay(bounds: Rectangle): boolean {
  return screen.getAllDisplays().some((display) => {
    const area = display.workArea;
    return (
      bounds.x < area.x + area.width &&
      bounds.x + bounds.width > area.x &&
      bounds.y < area.y + area.height &&
      bounds.y + bounds.height > area.y
    );
  });
}

/**
 * 读取上次保存的窗口状态（同步——在建窗前需立即拿到）。无文件/损坏/坐标已不可见
 * 时回退到默认尺寸并居中（不带 x/y，交给 OS 居中）。
 */
export function loadWindowState(): WindowState {
  let saved: Partial<WindowState> = {};
  try {
    saved = JSON.parse(
      readFileSync(stateFilePath(), "utf-8"),
    ) as Partial<WindowState>;
  } catch {
    // 首次启动 / 文件损坏 → 用默认值。
  }

  const width = typeof saved.width === "number" ? saved.width : DEFAULTS.width;
  const height =
    typeof saved.height === "number" ? saved.height : DEFAULTS.height;
  const state: WindowState = {
    width,
    height,
    isMaximized: saved.isMaximized === true,
  };

  if (typeof saved.x === "number" && typeof saved.y === "number") {
    // 仅当保存的矩形仍落在某块屏内才恢复坐标，否则居中。
    if (isVisibleOnSomeDisplay({ x: saved.x, y: saved.y, width, height })) {
      state.x = saved.x;
      state.y = saved.y;
    }
  }

  return state;
}

/**
 * 绑定窗口事件以持久化其状态。会话中 resize/move/最大化变化做 debounce 落盘；
 * `close` 时同步补一次（关窗后进程可能立即退出，异步写来不及）。
 *
 * 用 `getNormalBounds()` 取「还原态」矩形：即便当前最大化/最小化，记下的也是用户
 * 实际拖出来的大小，故下次取消最大化能回到正确尺寸。
 */
export function manageWindowState(window: BrowserWindow): void {
  let saveTimer: ReturnType<typeof setTimeout> | null = null;

  const snapshot = (): WindowState => {
    const bounds = window.getNormalBounds();
    return {
      width: bounds.width,
      height: bounds.height,
      x: bounds.x,
      y: bounds.y,
      isMaximized: window.isMaximized(),
    };
  };

  const persist = (): void => {
    try {
      writeFileSync(
        stateFilePath(),
        JSON.stringify(snapshot(), null, 2),
        "utf-8",
      );
    } catch (e) {
      console.error("[window-state] 持久化窗口状态失败:", e);
    }
  };

  const scheduleSave = (): void => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(persist, 400);
  };

  window.on("resize", scheduleSave);
  window.on("move", scheduleSave);
  window.on("maximize", scheduleSave);
  window.on("unmaximize", scheduleSave);
  window.on("close", () => {
    if (saveTimer) clearTimeout(saveTimer);
    persist();
  });
}
