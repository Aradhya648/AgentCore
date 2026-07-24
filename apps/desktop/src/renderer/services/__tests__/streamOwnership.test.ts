import { afterEach, describe, expect, it } from "vitest";
import {
  claimPrimaryStream,
  isPrimaryStreamIdle,
  onPrimaryStreamIdle,
  releasePrimaryStream,
  resetStreamOwnershipForTests,
  waitForPrimaryStreamIdle,
} from "../turns/streamOwnership";

const CID = "conv-ownership";

afterEach(() => {
  resetStreamOwnershipForTests();
});

describe("streamOwnership — 主路所有权栈", () => {
  it("claim / release 嵌套：内层释放后仍忙，外层释放才 idle", async () => {
    const outer = claimPrimaryStream(CID);
    const inner = claimPrimaryStream(CID);
    expect(isPrimaryStreamIdle(CID)).toBe(false);
    releasePrimaryStream(CID, inner);
    expect(isPrimaryStreamIdle(CID)).toBe(false);
    const idle = waitForPrimaryStreamIdle(CID);
    let resolved = false;
    void idle.then(() => {
      resolved = true;
    });
    await Promise.resolve();
    expect(resolved).toBe(false);
    releasePrimaryStream(CID, outer);
    await idle;
    expect(isPrimaryStreamIdle(CID)).toBe(true);
    expect(resolved).toBe(true);
  });

  it("错 token / 重复 release 不误伤其它持有者", () => {
    const a = claimPrimaryStream(CID);
    releasePrimaryStream(CID, "not-a-token");
    expect(isPrimaryStreamIdle(CID)).toBe(false);
    releasePrimaryStream(CID, a);
    expect(isPrimaryStreamIdle(CID)).toBe(true);
    releasePrimaryStream(CID, a); // no-op
    expect(isPrimaryStreamIdle(CID)).toBe(true);
  });

  it("onPrimaryStreamIdle 在 release 时空栈时触发", () => {
    const hits: number[] = [];
    const t = claimPrimaryStream(CID);
    const unsub = onPrimaryStreamIdle(CID, () => hits.push(1));
    expect(hits).toEqual([]);
    releasePrimaryStream(CID, t);
    expect(hits).toEqual([1]);
    unsub();
  });
});
