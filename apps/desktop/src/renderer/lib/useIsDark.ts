import { useEffect, useState } from "react";

/** Dark mode is class-based (`.dark` on an ancestor — see globals.css
 * `@custom-variant dark (&:is(.dark *))`), so we detect it from the DOM rather
 * than from a store, and observe class changes so theme-sensitive renderers
 * (e.g. mermaid) re-render on toggle. */
function detectDark(): boolean {
  if (typeof document === "undefined") return false;
  return (
    document.documentElement.classList.contains("dark") ||
    document.body.classList.contains("dark")
  );
}

export function useIsDark(): boolean {
  const [dark, setDark] = useState(detectDark);

  useEffect(() => {
    const update = () => setDark(detectDark());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
    });
    update();
    return () => observer.disconnect();
  }, []);

  return dark;
}
