import type { Vec3 } from "@agentcore/contract-types";
import contract from "@agentcore/protocol-conformance/fixtures/simulation-region-positions.json";

/** Authoritative town region anchors — must match backend REGION_POSITIONS. */
export const REGION_POSITIONS: Record<string, Vec3> = contract.regions;
