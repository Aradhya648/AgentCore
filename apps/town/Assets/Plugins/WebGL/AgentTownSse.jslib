// AgentTown WebGL SSE bridge.
//
// Ports the desktop R3F reference (apps/desktop/src/renderer/services/simulation/stream.ts):
// fetch() the run stream, read response.body as a ReadableStream, split the byte stream on
// blank lines (\n\n), and forward each frame's concatenated `data:` lines back to C#.
//
// Consumed by WebGlSseTransport.cs via [DllImport("__Internal")]. This is the WebGL
// connectivity path documented in docs/04-前端/AgentTown客户端.md §15.2
// (UnityWebRequest cannot read SSE incrementally in the browser).

mergeInto(LibraryManager.library, {
  AgentTownSseOpen: function (urlPtr, tokenPtr, onEvent, onStatus) {
    var url = UTF8ToString(urlPtr);
    var token = UTF8ToString(tokenPtr);

    // Abort any previous stream before starting a new one.
    if (typeof window !== "undefined" && window.__agentTownSse && window.__agentTownSse.controller) {
      try { window.__agentTownSse.controller.abort(); } catch (e) { /* ignore */ }
    }
    var controller = (typeof AbortController !== "undefined") ? new AbortController() : null;
    if (typeof window !== "undefined") {
      window.__agentTownSse = { controller: controller };
    }

    function sendString(cb, str) {
      var size = lengthBytesUTF8(str) + 1;
      var buffer = _malloc(size);
      stringToUTF8(str, buffer, size);
      {{{ makeDynCall('vi', 'cb') }}}(buffer);
      _free(buffer);
    }
    function status(state, detail) {
      sendString(onStatus, detail ? (state + "|" + detail) : state);
    }
    function emit(json) {
      sendString(onEvent, json);
    }

    status("connecting", "");

    var headers = { "Accept": "text/event-stream" };
    if (token) {
      headers["Authorization"] = "Bearer " + token;
    }

    fetch(url, {
      method: "GET",
      headers: headers,
      credentials: "include",
      signal: controller ? controller.signal : undefined
    }).then(function (response) {
      if (!response.ok || !response.body) {
        status("error", "SSE 连接失败 (" + response.status + ")");
        return;
      }
      status("connected", "");

      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";

      function pump() {
        return reader.read().then(function (result) {
          if (result.done) {
            status("idle", "");
            return;
          }
          buffer += decoder.decode(result.value, { stream: true });
          var frames = buffer.split("\n\n");
          buffer = frames.pop();
          for (var i = 0; i < frames.length; i++) {
            var lines = frames[i].split("\n");
            var dataLines = [];
            for (var j = 0; j < lines.length; j++) {
              var line = lines[j];
              if (line.charAt(line.length - 1) === "\r") {
                line = line.slice(0, -1);
              }
              if (line.indexOf("data:") === 0) {
                var d = line.slice(5);
                if (d.charAt(0) === " ") {
                  d = d.slice(1);
                }
                dataLines.push(d);
              }
            }
            if (dataLines.length > 0) {
              emit(dataLines.join("\n"));
            }
          }
          return pump();
        });
      }

      return pump();
    }).catch(function (err) {
      if (controller && controller.signal.aborted) {
        return;
      }
      status("error", (err && err.message) ? err.message : "SSE 中断");
    });
  },

  AgentTownSseClose: function () {
    if (typeof window !== "undefined" && window.__agentTownSse && window.__agentTownSse.controller) {
      try { window.__agentTownSse.controller.abort(); } catch (e) { /* ignore */ }
      window.__agentTownSse = null;
    }
  }
});
