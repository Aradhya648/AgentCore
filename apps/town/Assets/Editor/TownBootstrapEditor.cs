#if UNITY_EDITOR
using AgentTown.Town;
using UnityEditor;
using UnityEngine;

namespace AgentTown.Editor
{
    [CustomEditor(typeof(TownBootstrap))]
    public sealed class TownBootstrapEditor : UnityEditor.Editor
    {
        public override void OnInspectorGUI()
        {
            EditorGUILayout.HelpBox(
                "编辑模式下 Scene 视图是空的（设计如此）。\n" +
                "请点顶部 ▶ Play，然后看 Game 标签 — 小镇、NPC、HUD 会在运行时生成。",
                MessageType.Info);

            if (!EditorApplication.isPlaying && GUILayout.Button("▶ Play 并打开 Game 视图"))
            {
                EditorApplication.ExecuteMenuItem("Window/General/Game");
                EditorApplication.isPlaying = true;
            }

            DrawDefaultInspector();
        }
    }

    [InitializeOnLoad]
    internal static class AgentTownPlayViewFocus
    {
        static AgentTownPlayViewFocus()
        {
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
        }

        private static void OnPlayModeChanged(PlayModeStateChange state)
        {
            if (state == PlayModeStateChange.EnteredPlayMode)
            {
                EditorApplication.ExecuteMenuItem("Window/General/Game");
            }
        }
    }
}
#endif
