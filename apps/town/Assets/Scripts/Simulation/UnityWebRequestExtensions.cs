using System.Threading;
using System.Threading.Tasks;
using UnityEngine.Networking;

namespace AgentTown.Simulation
{
    internal static class UnityWebRequestExtensions
    {
        /// <summary>
        /// Await a <see cref="UnityWebRequest"/> as a <see cref="Task"/>. The completion
        /// callback is raised by Unity on the main thread, so continuations resume on the
        /// main thread — safe for touching Unity objects afterwards. Works on all targets
        /// including WebGL (unlike raw HttpClient).
        /// </summary>
        public static Task<UnityWebRequest> SendAsync(this UnityWebRequest request, CancellationToken ct = default)
        {
            var tcs = new TaskCompletionSource<UnityWebRequest>();
            UnityWebRequestAsyncOperation op = request.SendWebRequest();

            if (ct.CanBeCanceled)
            {
                ct.Register(() =>
                {
                    if (request != null && !request.isDone)
                    {
                        request.Abort();
                    }
                });
            }

            op.completed += _ => tcs.TrySetResult(request);
            return tcs.Task;
        }
    }
}
