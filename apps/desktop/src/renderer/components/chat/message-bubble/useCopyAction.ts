import { copyText } from "@/lib/clipboard";
import { useState } from "react";

export function useCopyAction(getText: () => string) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (await copyText(getText())) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };
  return { copied, onCopy };
}
