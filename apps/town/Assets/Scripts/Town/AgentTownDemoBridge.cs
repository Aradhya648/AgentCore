using System.Runtime.InteropServices;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// WebGL-only bridge so headless shoot scripts can detect Offline Demo readiness
    /// and current playhead tick (UI Toolkit labels are not exposed in the DOM).
    /// </summary>
    public static class AgentTownDemoBridge
    {
#if UNITY_WEBGL && !UNITY_EDITOR
        [DllImport("__Internal")]
        private static extern void AgentTownDemoSetReady(string packId, string displayName);

        [DllImport("__Internal")]
        private static extern void AgentTownDemoSetTick(int tick);

        [DllImport("__Internal")]
        private static extern void AgentTownDemoSetShoot(int enabled);

        [DllImport("__Internal")]
        private static extern void AgentTownDemoClearReady();
#endif

        public static void SetOfflineReady(string packId, string displayName)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            try
            {
                AgentTownDemoSetReady(packId ?? "", displayName ?? "");
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[AgentTown] Demo bridge SetReady failed: {e.Message}");
            }
#else
            _ = packId;
            _ = displayName;
#endif
        }

        public static void SetTick(int tick)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            try
            {
                AgentTownDemoSetTick(tick);
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[AgentTown] Demo bridge SetTick failed: {e.Message}");
            }
#else
            _ = tick;
#endif
        }

        public static void SetShootMode(bool enabled)
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            try
            {
                AgentTownDemoSetShoot(enabled ? 1 : 0);
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[AgentTown] Demo bridge SetShoot failed: {e.Message}");
            }
#else
            _ = enabled;
#endif
        }

        public static void Clear()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            try
            {
                AgentTownDemoClearReady();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[AgentTown] Demo bridge Clear failed: {e.Message}");
            }
#endif
        }
    }
}
