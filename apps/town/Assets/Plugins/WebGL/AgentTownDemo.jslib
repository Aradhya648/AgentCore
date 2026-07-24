// Offline Demo readiness probe for Playwright / shoot-webgl-demo.mjs.
// UI Toolkit text is not in the DOM; expose a small window flag instead.

mergeInto(LibraryManager.library, {
  AgentTownDemoSetReady: function (packIdPtr, displayNamePtr) {
    var packId = UTF8ToString(packIdPtr);
    var displayName = UTF8ToString(displayNamePtr);
    if (typeof window === "undefined") {
      return;
    }
    var prev = window.__agentTownDemo || {};
    window.__agentTownDemo = {
      ready: true,
      offline: true,
      packId: packId || "",
      displayName: displayName || "",
      tick: typeof prev.tick === "number" ? prev.tick : 0,
      shoot: !!prev.shoot,
      at: Date.now(),
    };
  },

  AgentTownDemoSetTick: function (tick) {
    if (typeof window === "undefined") {
      return;
    }
    if (!window.__agentTownDemo) {
      window.__agentTownDemo = {
        ready: false,
        offline: true,
        packId: "",
        displayName: "",
        tick: tick | 0,
        shoot: false,
        at: Date.now(),
      };
      return;
    }
    window.__agentTownDemo.tick = tick | 0;
    window.__agentTownDemo.at = Date.now();
  },

  AgentTownDemoSetShoot: function (enabled) {
    if (typeof window === "undefined") {
      return;
    }
    if (!window.__agentTownDemo) {
      window.__agentTownDemo = {
        ready: false,
        offline: true,
        packId: "",
        displayName: "",
        tick: 0,
        shoot: !!enabled,
        at: Date.now(),
      };
      return;
    }
    window.__agentTownDemo.shoot = !!enabled;
  },

  AgentTownDemoClearReady: function () {
    if (typeof window !== "undefined") {
      window.__agentTownDemo = null;
    }
  }
});
