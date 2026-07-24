#if UNITY_EDITOR
using System;
using AgentTown.Town;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace AgentTown.Editor
{
    /// <summary>
    /// Batchmode: setup → open Town.unity → Enter Play → wait for runtime town → quit.
    /// CLI: -executeMethod AgentTown.Editor.AgentTownBatchVerify.RunPlaySmokeFromBatch
    /// </summary>
    public static class AgentTownBatchVerify
    {
        private const string TownScenePath = "Assets/Scenes/Town.unity";
        private const double TimeoutSeconds = 45;

        private static double enteredPlayAt;
        private static bool handlersRegistered;
        private static bool smokePassed;
        private static bool smokeFailed;
        private static bool logHooked;

        public static void RunPlaySmokeFromBatch()
        {
            AgentTownProjectSetup.SetupFromBatch();
            EditorSceneManager.OpenScene(TownScenePath, OpenSceneMode.Single);

            if (!handlersRegistered)
            {
                EditorApplication.playModeStateChanged += OnPlayModeChanged;
                EditorApplication.update += OnEditorUpdate;
                handlersRegistered = true;
            }

            if (!logHooked)
            {
                Application.logMessageReceived += OnRuntimeLog;
                logHooked = true;
            }

            smokePassed = false;
            smokeFailed = false;
            enteredPlayAt = EditorApplication.timeSinceStartup;
            Debug.Log("[AgentTown] Play smoke: entering Play mode…");
            EditorApplication.EnterPlaymode();
        }

        private static void OnRuntimeLog(string condition, string stackTrace, LogType type)
        {
            if (!EditorApplication.isPlaying || smokePassed)
            {
                return;
            }

            if (condition.Contains("NavMesh baked over town ground", StringComparison.Ordinal))
            {
                Debug.Log("[AgentTown] Play smoke PASSED — runtime town built.");
                smokePassed = true;
                EditorApplication.isPlaying = false;
            }
        }

        private static void OnPlayModeChanged(PlayModeStateChange state)
        {
            if (state == PlayModeStateChange.EnteredPlayMode)
            {
                enteredPlayAt = EditorApplication.timeSinceStartup;
            }

            if (state == PlayModeStateChange.EnteredEditMode && smokePassed)
            {
                EditorApplication.Exit(0);
            }

            if (state == PlayModeStateChange.EnteredEditMode && smokeFailed)
            {
                EditorApplication.Exit(1);
            }
        }

        private static void OnEditorUpdate()
        {
            if (!EditorApplication.isPlaying)
            {
                return;
            }

            if (FindTownGround() != null)
            {
                Debug.Log("[AgentTown] Play smoke PASSED — TownGround + runtime town spawned.");
                smokePassed = true;
                EditorApplication.isPlaying = false;
                return;
            }

            if (EditorApplication.timeSinceStartup - enteredPlayAt > TimeoutSeconds)
            {
                Debug.LogError("[AgentTown] Play smoke FAILED — timed out waiting for TownGround.");
                smokeFailed = true;
                EditorApplication.isPlaying = false;
            }
        }

        private static GameObject FindTownGround()
        {
            GameObject byName = GameObject.Find("TownGround");
            if (byName != null)
            {
                return byName;
            }

            TownBuilder builder = UnityEngine.Object.FindFirstObjectByType<TownBuilder>();
            if (builder == null)
            {
                return null;
            }

            Transform ground = builder.transform.Find("TownGround");
            return ground != null ? ground.gameObject : null;
        }
    }
}
#endif
