import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge class names with Tailwind-aware conflict resolution — the shared helper
 * behind the `components/ui/` primitives. `clsx` flattens conditional / array
 * inputs; `tailwind-merge` then dedupes conflicting Tailwind utilities (last one
 * wins), so a caller's `className` can override a primitive's defaults instead of
 * producing two fighting classes.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
