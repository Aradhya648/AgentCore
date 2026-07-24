#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

namespace AgentTown.Town
{
    /// <summary>
    /// Player-loop FPS sampler for the graphics-enabled watch-floor gate (UT-16 / FE-19: "10 NPC ≥
    /// 30 FPS"). Editor-only, but lives in the runtime assembly on purpose: its
    /// <c>RuntimeInitializeOnLoadMethod</c> hook and <see cref="MonoBehaviour.Update"/> ride the
    /// PLAYER loop, which keeps ticking in batchmode Play — unlike <c>EditorApplication.update</c>,
    /// which the play-mode domain reload silently unsubscribes (see <c>AgentTownPerfGate</c>).
    ///
    /// <para>Armed by <c>AgentTownPerfGate.RunFromBatch</c> via <see cref="SessionState"/> (survives
    /// the reload). Once armed it waits for the town + its residents, warms up, measures average /
    /// worst-frame FPS over a fixed window, logs a verdict line the <c>perf-unity.ps1</c> wrapper
    /// greps for (<c>Perf gate PASSED</c> / <c>Perf gate FAILED</c>), and quits the editor with the
    /// matching exit code.</para>
    /// </summary>
    public sealed class AgentTownPerfProbe : MonoBehaviour
    {
        /// <summary>SessionState flag set by the editor entry before <c>EnterPlaymode</c>.</summary>
        public const string SessionKey = "AgentTown.PerfGate.Armed";

        private const string GroundName = "TownGround";
        private const int TargetNpc = 10;
        private const float FloorFps = 30f;
        private const float WarmupSeconds = 3f;
        private const float WindowSeconds = 6f;
        private const float TimeoutSeconds = 120f;

        private enum Phase
        {
            WaitTown,
            Warmup,
            Measure,
            Exiting,
        }

        private Phase phase = Phase.WaitTown;
        private float startTime;
        private float phaseStart;
        private int windowStartFrame;
        private float windowStartTime;
        private float worstFrameSec;
        private int measuredNpc;
        private int exitCode;
        private int exitDelayFrames;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void SpawnIfArmed()
        {
            if (!SessionState.GetBool(SessionKey, false))
            {
                return;
            }

            // Disarm now so a later manual Play in the same editor session never self-exits.
            SessionState.SetBool(SessionKey, false);

            var go = new GameObject(nameof(AgentTownPerfProbe));
            DontDestroyOnLoad(go);
            go.AddComponent<AgentTownPerfProbe>();
        }

        private void Start()
        {
            startTime = Time.realtimeSinceStartup;
            phaseStart = startTime;
        }

        private void Update()
        {
            float now = Time.realtimeSinceStartup;

            if (phase == Phase.Exiting)
            {
                if (--exitDelayFrames <= 0)
                {
                    EditorApplication.Exit(exitCode);
                }

                return;
            }

            if (now - startTime > TimeoutSeconds)
            {
                Fail($"timed out in phase {phase} after {TimeoutSeconds:0}s");
                return;
            }

            switch (phase)
            {
                case Phase.WaitTown:
                    if (TownReady(out int npc))
                    {
                        measuredNpc = npc;
                        phase = Phase.Warmup;
                        phaseStart = now;
                        Debug.Log(
                            $"[AgentTown] Perf gate: town ready ({npc} NPC) — warming up {WarmupSeconds:0.0}s…");
                    }

                    break;

                case Phase.Warmup:
                    if (now - phaseStart >= WarmupSeconds)
                    {
                        phase = Phase.Measure;
                        windowStartFrame = Time.frameCount;
                        windowStartTime = now;
                        worstFrameSec = 0f;
                        Debug.Log($"[AgentTown] Perf gate: measuring {WindowSeconds:0.0}s…");
                    }

                    break;

                case Phase.Measure:
                    float dt = Time.unscaledDeltaTime;
                    if (dt > worstFrameSec)
                    {
                        worstFrameSec = dt;
                    }

                    if (now - windowStartTime >= WindowSeconds)
                    {
                        FinishMeasurement(now);
                    }

                    break;
            }
        }

        private void FinishMeasurement(float now)
        {
            int frames = Time.frameCount - windowStartFrame;
            float elapsed = now - windowStartTime;
            double avgFps = elapsed > 0 ? frames / elapsed : 0;
            double worstFps = worstFrameSec > 0 ? 1.0 / worstFrameSec : 0;

            Debug.Log(
                $"[AgentTown] Perf gate result: avg={avgFps:0.0} FPS, worst-frame={worstFps:0.0} FPS " +
                $"({frames} frames / {elapsed:0.00}s, {measuredNpc} NPC, floor {FloorFps:0} FPS)");

            if (measuredNpc < TargetNpc)
            {
                Fail($"only {measuredNpc} NPC (< {TargetNpc}) — load not representative");
                return;
            }

            if (avgFps + 1e-3 < FloorFps)
            {
                Fail($"avg {avgFps:0.0} FPS < {FloorFps:0} FPS floor");
                return;
            }

            Debug.Log("[AgentTown] Perf gate PASSED");
            ScheduleExit(0);
        }

        private void Fail(string reason)
        {
            Debug.LogError($"[AgentTown] Perf gate FAILED — {reason}.");
            ScheduleExit(1);
        }

        // Give Debug.Log a few frames to flush to the -logFile before the process terminates, so the
        // wrapper reliably greps the verdict line even if the editor exits immediately after.
        private void ScheduleExit(int code)
        {
            exitCode = code;
            exitDelayFrames = 3;
            phase = Phase.Exiting;
        }

        private static bool TownReady(out int npcCount)
        {
            npcCount = 0;
            if (GameObject.Find(GroundName) == null)
            {
                return false;
            }

            TownNpc[] npcs = FindObjectsByType<TownNpc>(FindObjectsSortMode.None);
            npcCount = npcs != null ? npcs.Length : 0;
            return npcCount >= TargetNpc;
        }
    }
}
#endif
