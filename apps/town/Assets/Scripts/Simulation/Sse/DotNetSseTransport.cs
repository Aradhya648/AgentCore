#if !UNITY_WEBGL || UNITY_EDITOR
using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace AgentTown.Simulation
{
    /// <summary>
    /// Editor / desktop-standalone SSE via <see cref="HttpClient"/> streaming — the ".NET
    /// 流式路径" of §15.2. Reads the response body incrementally on a background task and
    /// forwards decoded frames through the callbacks; <see cref="SimulationSseClient"/>
    /// marshals them back to the main thread.
    /// </summary>
    internal sealed class DotNetSseTransport : ISimulationSseTransport
    {
        // Infinite timeout: SSE is a long-lived stream; per-read cancellation is via the token.
        private static readonly HttpClient Client = new HttpClient { Timeout = Timeout.InfiniteTimeSpan };

        private CancellationTokenSource cts;

        public void Connect(string url, string bearerToken, Action<string> onEventJson, Action<string, string> onStatus)
        {
            Disconnect();
            cts = new CancellationTokenSource();
            CancellationToken token = cts.Token;
            _ = Task.Run(() => PumpAsync(url, bearerToken, onEventJson, onStatus, token), token);
        }

        public void Disconnect()
        {
            try
            {
                cts?.Cancel();
                cts?.Dispose();
            }
            catch (ObjectDisposedException)
            {
                // already disposed — ignore
            }

            cts = null;
        }

        private static async Task PumpAsync(
            string url,
            string bearerToken,
            Action<string> onEventJson,
            Action<string, string> onStatus,
            CancellationToken ct)
        {
            onStatus("connecting", "");

            HttpResponseMessage response;
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, url);
                request.Headers.Accept.ParseAdd("text/event-stream");
                if (!string.IsNullOrEmpty(bearerToken))
                {
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
                }

                response = await Client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception e)
            {
                onStatus("error", $"无法连接模拟 SSE 流: {e.Message}");
                return;
            }

            using (response)
            {
                if (!response.IsSuccessStatusCode)
                {
                    onStatus("error", $"SSE 连接失败 ({(int)response.StatusCode})");
                    return;
                }

                onStatus("connected", "");

                try
                {
                    using Stream stream = await response.Content.ReadAsStreamAsync();
                    using var reader = new StreamReader(stream, Encoding.UTF8);

                    string buffer = "";
                    var chunk = new char[4096];
                    while (!ct.IsCancellationRequested)
                    {
                        int read = await reader.ReadAsync(chunk, 0, chunk.Length);
                        if (read <= 0)
                        {
                            break;
                        }

                        buffer += new string(chunk, 0, read);

                        int separator;
                        while ((separator = buffer.IndexOf("\n\n", StringComparison.Ordinal)) >= 0)
                        {
                            string frame = buffer.Substring(0, separator);
                            buffer = buffer.Substring(separator + 2);
                            string json = SseFrame.ExtractData(frame);
                            if (json != null)
                            {
                                onEventJson(json);
                            }
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (Exception e)
                {
                    if (!ct.IsCancellationRequested)
                    {
                        onStatus("error", e.Message);
                    }

                    return;
                }
            }

            if (!ct.IsCancellationRequested)
            {
                onStatus("idle", "");
            }
        }
    }
}
#endif
