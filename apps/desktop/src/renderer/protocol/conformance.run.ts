// `pnpm conformance` entry for the desktop fold (前端技术与架构 §十二).
// Runs the real production-sourced fold adapter against every backend-exported golden
// vector via the shared harness — same gate as mobile, no hand-maintained import list.
import { runConformance } from "@agentcore/protocol-conformance";
import { foldToProjectedTurn } from "./conformanceFold";

const { failed } = runConformance({
  name: "desktop",
  fold: foldToProjectedTurn,
});
process.exit(failed === 0 ? 0 : 1);
