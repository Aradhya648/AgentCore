using System;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Platform SSE transport. Two implementations exist:
    /// <list type="bullet">
    /// <item><see cref="DotNetSseTransport"/> — Editor / desktop standalone, HttpClient streaming.</item>
    /// <item><c>WebGlSseTransport</c> — browser <c>fetch</c> + <c>ReadableStream</c> via a <c>.jslib</c>.</item>
    /// </list>
    /// Callbacks may fire on a background thread (DotNet path) or the browser main thread
    /// (WebGL path); <see cref="SimulationSseClient"/> marshals both onto the Unity main
    /// thread via <see cref="SimulationSseClient.Poll"/>.
    /// </summary>
    internal interface ISimulationSseTransport
    {
        /// <param name="onEventJson">Called with the decoded JSON body of one SSE frame (data: lines joined).</param>
        /// <param name="onStatus">Called with (status, detail) as the stream state changes.</param>
        void Connect(string url, string bearerToken, Action<string> onEventJson, Action<string, string> onStatus);

        void Disconnect();
    }
}
