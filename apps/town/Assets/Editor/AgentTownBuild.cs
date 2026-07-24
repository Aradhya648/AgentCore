#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace AgentTown.Editor
{
    /// <summary>
    /// Batch build entry points for AgentTown Windows / WebGL players.
    /// <list type="bullet">
    /// <item><c>-executeMethod AgentTown.Editor.AgentTownBuild.BuildWindows</c></item>
    /// <item><c>-executeMethod AgentTown.Editor.AgentTownBuild.BuildWebGL</c></item>
    /// </list>
    /// </summary>
    public static class AgentTownBuild
    {
        private const string TownScene = "Assets/Scenes/Town.unity";
        private const string WindowsOut = "Builds/Windows/AgentTown.exe";
        private const string WebGlOutDir = "Builds/WebGL";

        [MenuItem("AgentTown/Build/Windows")]
        public static void BuildWindows() => Build(BuildTarget.StandaloneWindows64, WindowsOut, false, development: true);

        [MenuItem("AgentTown/Build/WebGL")]
        // Release WebGL: Development Console overlays the canvas and blocks shoot screenshots.
        public static void BuildWebGL() => Build(BuildTarget.WebGL, WebGlOutDir, true, development: false);

        private static void Build(BuildTarget target, string relativeOutput, bool outputIsDirectory, bool development)
        {
            AgentTownProjectSetup.SetupFromBatch();

            string[] scenes = EditorBuildSettings.scenes
                .Where(s => s.enabled && !string.IsNullOrEmpty(s.path))
                .Select(s => s.path)
                .ToArray();
            if (scenes.Length == 0)
            {
                if (!File.Exists(TownScene))
                {
                    throw new FileNotFoundException("Town scene missing", TownScene);
                }

                scenes = new[] { TownScene };
            }

            string projectRoot = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            string outputPath = Path.Combine(projectRoot, relativeOutput.Replace('/', Path.DirectorySeparatorChar));
            string outputDir = outputIsDirectory ? outputPath : Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(outputDir))
            {
                Directory.CreateDirectory(outputDir);
            }

            var options = new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = outputPath,
                target = target,
                options = development ? BuildOptions.Development : BuildOptions.None,
            };

            Debug.Log($"[AgentTown] Building {target} → {outputPath}");
            BuildReport report = BuildPipeline.BuildPlayer(options);
            BuildSummary summary = report.summary;
            if (summary.result != BuildResult.Succeeded)
            {
                throw new Exception(
                    $"[AgentTown] Build {target} failed: {summary.result} " +
                    $"(errors={summary.totalErrors}, warnings={summary.totalWarnings})");
            }

            Debug.Log(
                $"[AgentTown] Build {target} OK in {summary.totalTime.TotalSeconds:F1}s → {outputPath}");
            // batchmode callers rely on non-zero exit; Unity quits via -quit.
        }
    }
}
#endif
