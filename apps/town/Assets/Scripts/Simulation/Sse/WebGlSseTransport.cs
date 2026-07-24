#if UNITY_WEBGL && !UNITY_EDITOR
using System;
using System.Runtime.InteropServices;
using AOT;

namespace AgentTown.Simulation
{
    /// <summary>
    /// WebGL SSE transport bridging to <c>AgentTownSse.jslib</c> (browser <c>fetch</c> +
    /// <c>ReadableStream</c>, ported from the desktop R3F <c>stream.ts</c>). This is the
    /// key WebGL connectivity code the §15.2 spike depends on: UnityWebRequest cannot read
    /// SSE incrementally in the browser, so a native JS bridge is required.
    ///
    /// <para>JS invokes the callbacks on the browser main thread; they route to the active
    /// instance and the client's Poll() drains them (same contract as the DotNet path).</para>
    /// </summary>
    internal sealed class WebGlSseTransport : ISimulationSseTransport
    {
        [DllImport("__Internal")]
        private static extern void AgentTownSseOpen(string url, string token, Action<IntPtr> onEvent, Action<IntPtr> onStatus);

        [DllImport("__Internal")]
        private static extern void AgentTownSseClose();

        // Static so the marshalled function pointers survive GC for the stream's lifetime.
        private static readonly Action<IntPtr> EventCallback = OnEventStatic;
        private static readonly Action<IntPtr> StatusCallback = OnStatusStatic;
        private static WebGlSseTransport active;

        private Action<string> onEventJson;
        private Action<string, string> onStatus;

        public void Connect(string url, string bearerToken, Action<string> onEventJson, Action<string, string> onStatus)
        {
            this.onEventJson = onEventJson;
            this.onStatus = onStatus;
            active = this;
            AgentTownSseOpen(url, bearerToken ?? "", EventCallback, StatusCallback);
        }

        public void Disconnect()
        {
            if (active == this)
            {
                active = null;
            }

            AgentTownSseClose();
        }

        [MonoPInvokeCallback(typeof(Action<IntPtr>))]
        private static void OnEventStatic(IntPtr ptr)
        {
            string json = Marshal.PtrToStringUTF8(ptr);
            if (!string.IsNullOrEmpty(json))
            {
                active?.onEventJson?.Invoke(json);
            }
        }

        [MonoPInvokeCallback(typeof(Action<IntPtr>))]
        private static void OnStatusStatic(IntPtr ptr)
        {
            string raw = Marshal.PtrToStringUTF8(ptr);
            if (raw == null)
            {
                return;
            }

            int sep = raw.IndexOf('|');
            if (sep >= 0)
            {
                active?.onStatus?.Invoke(raw.Substring(0, sep), raw.Substring(sep + 1));
            }
            else
            {
                active?.onStatus?.Invoke(raw, "");
            }
        }
    }
}
#endif
