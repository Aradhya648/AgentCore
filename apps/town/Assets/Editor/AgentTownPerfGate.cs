#if UNITY_EDITOR
using AgentTown.Town;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AgentTown.Editor
{
    /// <summary>
    /// Graphics-enabled play-mode FPS gate for the watch floor (UT-16 / FE-19: "10 NPC ≥ 30 FPS
    /// 中端 GPU"). Opens Town.unity, arms <see cref="AgentTownPerfProbe"/>, and enters Play WITH a
    /// render device. The measurement itself runs on the PLAYER loop (the probe MonoBehaviour), not
    /// in this editor entry — see the note below. CLI:
    /// <c>-executeMethod AgentTown.Editor.AgentTownPerfGate.RunFromBatch</c>
    /// (driven by <c>apps/town/scripts/perf-unity.ps1</c> / <c>pnpm town:perf</c>).
    ///
    /// <para><b>Why a player-loop probe, not EditorApplication.update:</b> entering Play does a
    /// domain reload that clears editor-callback subscriptions (and batchmode has no editor GUI loop
    /// to pump <c>EditorApplication.update</c> during Play), so an editor-driven gate never ticks
    /// once Play starts — it hangs and emits no verdict. The player loop DOES run in batchmode Play
    /// (that is what builds the town), so the probe rides it. The arm flag lives in
    /// <see cref="SessionState"/> which survives the reload; <see cref="AgentTownPerfProbe"/> reads
    /// it via <c>RuntimeInitializeOnLoadMethod</c> and self-reports the verdict + exit code.</para>
    ///
    /// <para><b>Why not in town:verify:</b> the headless smoke runs <c>-nographics</c> (no GPU), so
    /// an FPS number there would be CPU-only and trivially green — a fake gate. This gate therefore
    /// runs WITHOUT <c>-nographics</c>. Editor play-mode FPS is a conservative lower bound versus a
    /// standalone build on the same GPU, and the run is capped by <c>Application.targetFrameRate</c>
    /// (60) — so a healthy town reads ~60 and the 30 floor keeps real headroom.</para>
    /// </summary>
    public static class AgentTownPerfGate
    {
        private const string TownScenePath = "Assets/Scenes/Town.unity";

        public static void RunFromBatch()
        {
            AgentTownProjectSetup.SetupFromBatch();
            EditorSceneManager.OpenScene(TownScenePath, OpenSceneMode.Single);

            // SessionState survives the play-mode domain reload; the probe reads it on the player loop.
            SessionState.SetBool(AgentTownPerfProbe.SessionKey, true);
            Debug.Log("[AgentTown] Perf gate: entering Play mode (graphics on)…");
            EditorApplication.EnterPlaymode();
        }
    }
}
#endif
