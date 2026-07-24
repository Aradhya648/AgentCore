using System;
using System.Collections.Concurrent;

namespace AgentTown.Simulation
{
    /// <summary>
    /// SSE client for <c>GET /v1/simulation/runs/{id}/stream</c> (§5 P1). Selects a
    /// platform transport (HttpClient streaming on Editor/standalone; a <c>.jslib</c>
    /// fetch bridge on WebGL) and exposes a uniform, main-thread event surface.
    ///
    /// <para>Transport callbacks may arrive off the main thread, so they are queued;
    /// <see cref="Poll"/> drains the queue on the caller's thread (drive it from a
    /// MonoBehaviour <c>Update</c> — or <see cref="SimulationSession.Update"/>).</para>
    /// </summary>
    public sealed class SimulationSseClient
    {
        private readonly struct Signal
        {
            public readonly bool IsStatus;
            public readonly string A;
            public readonly string B;

            public Signal(bool isStatus, string a, string b)
            {
                IsStatus = isStatus;
                A = a;
                B = b;
            }
        }

        private readonly ConcurrentQueue<Signal> queue = new();

        private ISimulationSseTransport transport;
        private string apiBase = "";
        private string accessToken = "";
        private string runId = "";

        public string StreamStatus { get; private set; } = "idle";
        public bool IsConnected { get; private set; }

        /// <summary>Raised on <see cref="Poll"/> for each decoded SSE event.</summary>
        public event Action<SimSseEvent> OnEvent;

        /// <summary>Raised on <see cref="Poll"/> as (status, detail) when the stream state changes.</summary>
        public event Action<string, string> OnStreamStatusChanged;

        public void Configure(string apiBaseUrl, string token, string run)
        {
            apiBase = TrimTrailingSlashes(apiBaseUrl ?? "");
            accessToken = token ?? "";
            runId = run ?? "";
        }

        public void Connect()
        {
            if (string.IsNullOrEmpty(runId) || string.IsNullOrEmpty(apiBase))
            {
                EnqueueStatus("error", "Missing run id or API base");
                return;
            }

            Disconnect();
            transport = CreateTransport();
            string url = $"{apiBase}/v1/simulation/runs/{Uri.EscapeDataString(runId)}/stream";
            transport.Connect(url, accessToken, EnqueueEvent, EnqueueStatus);
        }

        public void Disconnect()
        {
            transport?.Disconnect();
            transport = null;
            EnqueueStatus("idle", "");
        }

        /// <summary>Drain queued transport signals on the calling thread and raise events.</summary>
        public void Poll()
        {
            while (queue.TryDequeue(out Signal signal))
            {
                if (signal.IsStatus)
                {
                    StreamStatus = signal.A;
                    IsConnected = signal.A == "connected";
                    OnStreamStatusChanged?.Invoke(signal.A, signal.B);
                }
                else if (SimJson.TryDeserialize<SimSseEvent>(signal.A, out SimSseEvent evt)
                         && !string.IsNullOrEmpty(evt.Type))
                {
                    OnEvent?.Invoke(evt);
                }
            }
        }

        private void EnqueueEvent(string json) => queue.Enqueue(new Signal(false, json, null));

        private void EnqueueStatus(string status, string detail) => queue.Enqueue(new Signal(true, status, detail));

        private static ISimulationSseTransport CreateTransport()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            return new WebGlSseTransport();
#else
            return new DotNetSseTransport();
#endif
        }

        private static string TrimTrailingSlashes(string value)
        {
            string result = value;
            while (result.EndsWith("/", StringComparison.Ordinal))
            {
                result = result.Substring(0, result.Length - 1);
            }

            return result;
        }
    }
}
