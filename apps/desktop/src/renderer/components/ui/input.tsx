import { cn } from "@/lib/utils";
import {
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
  forwardRef,
} from "react";

const fieldClass =
  "rounded-lg border border-border bg-background text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-40";

export const Input = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function Input({ className, ...props }, ref) {
  return (
    <input
      ref={ref}
      className={cn(fieldClass, "h-8 px-2.5", className)}
      {...props}
    />
  );
});

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      className={cn(fieldClass, "resize-none px-2.5 py-1.5 text-xs", className)}
      {...props}
    />
  );
});
