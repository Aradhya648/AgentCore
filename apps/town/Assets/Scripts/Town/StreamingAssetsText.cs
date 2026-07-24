using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using AgentTown.Simulation;
using UnityEngine;
using UnityEngine.Networking;

namespace AgentTown.Town
{
    /// <summary>
    /// Loads text assets from <c>StreamingAssets</c> on every target (§6.6 WebGL note).
    ///
    /// <para>WebGL cannot use <see cref="File"/> IO — <see cref="Application.streamingAssetsPath"/>
    /// resolves to an <c>http(s)://…/StreamingAssets</c> URL served alongside the build, so we
    /// always go through <see cref="UnityWebRequest"/>. On desktop / Editor the same path is a
    /// local directory, which <see cref="UnityWebRequest"/> reads via a <c>file://</c> URI. This
    /// keeps the town builder and persona loader free of desktop-only APIs.</para>
    /// </summary>
    public static class StreamingAssetsText
    {
        /// <summary>Resolve a StreamingAssets-relative path (e.g. <c>Fixtures/foo.json</c>) into a request URI.</summary>
        public static string ResolveUri(string relativePath)
        {
            string combined = Path.Combine(Application.streamingAssetsPath, relativePath);

#if UNITY_WEBGL && !UNITY_EDITOR
            // streamingAssetsPath is already a fully-qualified URL under WebGL.
            return combined.Replace('\\', '/');
#else
            // Local filesystem path → file:// URI (handles spaces / non-ASCII correctly).
            return new Uri(combined).AbsoluteUri;
#endif
        }

        /// <summary>
        /// Fetch a StreamingAssets text file; returns <c>null</c> on failure (logged). Safe to
        /// await from Unity async flows — <see cref="UnityWebRequestExtensions.SendAsync"/> resumes
        /// the continuation on the main thread.
        /// </summary>
        public static async Task<string> LoadAsync(string relativePath, CancellationToken ct = default)
        {
            string uri = ResolveUri(relativePath);
            using UnityWebRequest request = UnityWebRequest.Get(uri);
            await request.SendAsync(ct);

            if (ct.IsCancellationRequested)
            {
                return null;
            }

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"[AgentTown] StreamingAssets load failed ({uri}): {request.error}");
                return null;
            }

            return request.downloadHandler.text;
        }
    }
}
