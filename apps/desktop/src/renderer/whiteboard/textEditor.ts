/**
 * TextEditor — the whiteboard's text-edit overlay (AI协作白板.md §六 自研引擎架构).
 *
 * A floating <textarea> positioned over the canvas for creating a new text element or editing
 * an existing element's label. On blur/Escape it commits the trimmed value back to the host
 * (the engine), which owns the scene + history. Split out of {@link WhiteboardEngine} so the
 * DOM-overlay concern stays off the canvas controller.
 */

import { elementBox } from "./geometry";
import type { SceneElement, Viewport } from "./types";

/** What the editor hands back when an edit ends. `id` is the element being edited, or null
 * to create a brand-new text element at `world`. `text` is already trimmed. */
export interface TextCommit {
  id: string | null;
  world: [number, number];
  text: string;
}

export interface TextEditHost {
  /** Positioned container the textarea is appended to (the canvas overlay layer). */
  readonly container: HTMLElement;
  getViewport(): Viewport;
  /** Apply the committed text to the scene (the host owns elements + history). */
  onCommitText(commit: TextCommit): void;
  /** Re-render after the overlay opens/closes so the underlying element hides/shows. */
  requestRender(): void;
}

export class TextEditor {
  private overlay: HTMLTextAreaElement | null = null;
  private editing: { id: string | null; world: [number, number] } | null = null;

  constructor(private readonly host: TextEditHost) {}

  /** Id of the element currently being edited, so the renderer can hide its baked text. */
  get editingId(): string | null {
    return this.editing?.id ?? null;
  }

  /** Open the overlay to edit `el`, or to create a new text element at `world` when null.
   * Any in-flight edit is committed first. */
  begin(el: SceneElement | null, world: [number, number]): void {
    this.commit();
    const vp = this.host.getViewport();
    this.editing = { id: el?.id ?? null, world };

    const ta = document.createElement("textarea");
    ta.value = el?.text ?? "";
    ta.spellcheck = false;
    ta.rows = 1;
    const fontSize = (el?.fontSize ?? 18) * vp.zoom;
    const screenX = world[0] * vp.zoom + vp.panX;
    const screenY = world[1] * vp.zoom + vp.panY;
    Object.assign(ta.style, {
      position: "absolute",
      left: `${el ? elementBox(el).x * vp.zoom + vp.panX : screenX}px`,
      top: `${el ? elementBox(el).y * vp.zoom + vp.panY : screenY}px`,
      minWidth: "80px",
      maxWidth: "480px",
      fontSize: `${fontSize}px`,
      lineHeight: "1.3",
      padding: "2px 4px",
      margin: "0",
      border: "1px solid var(--primary)",
      borderRadius: "6px",
      outline: "none",
      resize: "none",
      overflow: "hidden",
      background: "var(--background)",
      color: "var(--foreground)",
      font: `${fontSize}px ui-sans-serif, system-ui, sans-serif`,
      zIndex: "10",
      boxShadow: "0 2px 8px var(--overlay)",
    });
    ta.addEventListener("input", () => {
      ta.style.height = "auto";
      ta.style.height = `${ta.scrollHeight}px`;
    });
    ta.addEventListener("blur", () => this.commit());
    ta.addEventListener("keydown", (ev) => {
      // Keep canvas shortcuts (tool keys, delete, …) from firing while typing.
      ev.stopPropagation();
      if (ev.key === "Escape") {
        ev.preventDefault();
        this.commit();
      }
    });
    this.host.container.appendChild(ta);
    this.overlay = ta;
    requestAnimationFrame(() => {
      ta.focus();
      ta.style.height = `${ta.scrollHeight}px`;
    });
    this.host.requestRender();
  }

  /** Commit the current edit (if any) to the host and tear down the overlay. No-op when
   * nothing is being edited. */
  commit(): void {
    const ta = this.overlay;
    const editing = this.editing;
    if (!ta || !editing) return;
    this.overlay = null;
    this.editing = null;
    const text = ta.value.trim();
    ta.remove();
    this.host.onCommitText({ id: editing.id, world: editing.world, text });
  }

  /** Remove the overlay without committing (engine teardown). */
  destroy(): void {
    this.overlay?.remove();
    this.overlay = null;
    this.editing = null;
  }
}
