import { CONTENT_CHAPTERS } from "@/pages/toolbox/manual/content";
import { resolveEmbed } from "@/pages/toolbox/manual/embedRegistry";
import { describe, expect, it } from "vitest";

describe("content embeds", () => {
  it("every embed key used by content resolves in the registry", () => {
    for (const chapter of CONTENT_CHAPTERS) {
      for (const section of chapter.sections) {
        for (const block of section.blocks) {
          if (block.type !== "embed") continue;
          expect(
            resolveEmbed(block.key),
            `unresolved embed "${block.key}" in ${chapter.id}/${section.id}`,
          ).toBeDefined();
        }
      }
    }
  });
});
