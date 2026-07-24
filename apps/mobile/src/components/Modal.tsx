import { type ReactNode, useEffect, useRef } from "react";

/**
 * Native <dialog> modal shell (touch-native overlays · a11y baseline).
 *
 * `showModal()` on mount buys a real focus trap, an inert background, and
 * Esc-to-close for free — the things the old `<div role="dialog">` + manual
 * `.backdrop` overlays only faked. The dim is the UA `::backdrop` pseudo-element
 * (styled per-variant in styles.css), so there is no backdrop element to manage.
 *
 * Callers mount it only while open (`{cond && <Modal/>}`); unmounting closes it.
 * A pointer click that lands on the dialog box itself but outside its content
 * rect is a backdrop tap → dismiss; clicks inside the panel (and keyboard
 * activations bubbling from child controls) never close it — matching the old
 * backdrop-click / `stopPropagation` behaviour exactly.
 */
export function Modal({
  className,
  onClose,
  label,
  children,
}: {
  className?: string;
  onClose: () => void;
  label?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dlg = ref.current;
    if (!dlg || dlg.open) return;
    dlg.showModal();
    return () => {
      if (dlg.open) dlg.close();
    };
  }, []);
  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: onClick is only the backdrop tap-to-dismiss; the keyboard dismissal path is Esc, handled natively by <dialog> and wired through onCancel below — Biome just doesn't treat onCancel as the keyboard pair for onClick.
    <dialog
      ref={ref}
      className={className}
      aria-label={label}
      onCancel={(e) => {
        // Esc fires `cancel` then `close`; drive React so app state stays in
        // sync instead of leaving a closed-but-still-mounted dialog.
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        // Only a real pointer click on the dialog element itself (its ::backdrop
        // or its own padding) — never a child click or a keyboard activation
        // bubbling up (those target a child, not currentTarget).
        if (e.target !== e.currentTarget) return;
        const r = e.currentTarget.getBoundingClientRect();
        const outside =
          e.clientX < r.left ||
          e.clientX > r.right ||
          e.clientY < r.top ||
          e.clientY > r.bottom;
        if (outside) onClose();
      }}
    >
      {children}
    </dialog>
  );
}
