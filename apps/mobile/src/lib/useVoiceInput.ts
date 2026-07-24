// 语音输入 (手机端 · 桌面对齐) —— 点麦克风录音 → 转写文本回填 composer 供用户编辑再发。
//
// 运行时双路分派 (cross-platform-frontend.mdc「手机 = 桌面 − 物理做不到」；语音两端都能做，故各
// 端独立实现同一产品形态)：
//   · 原生壳 (Capacitor.isNativePlatform())     → @capgo/capacitor-speech-recognition 原生识别。
//   · Web 浏览器                                → 降级用 Web Speech API (webkitSpeechRecognition)。
//   · 两者都不可用                              → isSupported=false，调用方隐藏麦克风按钮，不报错。
//
// 契约边界：语音只产出文本回填输入框，绝不碰 SSE / 协议 / ProjectedTurn / fold。零共享桌面业务逻辑
// (不 import 桌面代码)——交互形态 (idle/recording/processing 状态机、interim 实时文本、录音时长、
// 取消、5 分钟上限、中文错误、意外中断自动重启) 参照桌面 useVoiceInput.ts 但此处手机独立落地。
import { Capacitor } from "@capacitor/core";
import {
  SpeechRecognition,
  type SpeechRecognitionErrorEvent,
  type SpeechRecognitionListeningEvent,
  type SpeechRecognitionPartialResultEvent,
} from "@capgo/capacitor-speech-recognition";
import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceInputState = "idle" | "recording" | "processing";

const MAX_DURATION_MS = 5 * 60 * 1000;
/** How long a transient error caption lingers before auto-clearing (手机无 toast 原语). */
const ERROR_LINGER_MS = 5000;

// —— Web Speech API 最小类型 (lib.dom 未内建 webkitSpeechRecognition) ——
interface WebSpeechAlternative {
  transcript: string;
  confidence: number;
}
interface WebSpeechResult {
  isFinal: boolean;
  length: number;
  item(index: number): WebSpeechAlternative;
  [index: number]: WebSpeechAlternative;
}
interface WebSpeechResultList {
  length: number;
  item(index: number): WebSpeechResult;
  [index: number]: WebSpeechResult;
}
interface WebSpeechEvent extends Event {
  resultIndex: number;
  results: WebSpeechResultList;
}
interface WebSpeechErrorEvent extends Event {
  error: string;
  message?: string;
}
interface WebSpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: WebSpeechEvent) => void) | null;
  onerror: ((event: WebSpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
}
type WebSpeechCtor = new () => WebSpeechRecognition;

function getWebSpeech(): WebSpeechCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    webkitSpeechRecognition?: WebSpeechCtor;
    SpeechRecognition?: WebSpeechCtor;
  };
  return w.webkitSpeechRecognition ?? w.SpeechRecognition ?? null;
}

/** Web Speech 错误码 → 中文提示 (返回 null = 静默，如用户主动 abort)。 */
function mapWebError(error: string): string | null {
  switch (error) {
    case "not-allowed":
    case "service-not-allowed":
      return "麦克风权限被拒绝，请在系统设置中允许访问";
    case "audio-capture":
      return "未检测到麦克风设备";
    case "network":
      return "网络错误，语音转写需要联网";
    case "no-speech":
      return "未检测到语音，请重试";
    case "aborted":
      return null;
    default:
      return "语音转写失败，请重试";
  }
}

/** 原生识别错误码 → 中文提示 (返回 null = 交给 listeningState 自动重启，不打扰用户)。
 *  Android 用数值码；iOS 用字符串码，未知一律走通用兜底。 */
function mapNativeError(code: string): string | null {
  switch (code) {
    case "9": // ERROR_INSUFFICIENT_PERMISSIONS
      return "麦克风权限被拒绝，请在系统设置中允许访问";
    case "1": // ERROR_NETWORK_TIMEOUT
    case "2": // ERROR_NETWORK
      return "网络错误，语音转写需要联网";
    case "3": // ERROR_AUDIO
      return "未检测到麦克风设备";
    case "6": // ERROR_SPEECH_TIMEOUT
    case "7": // ERROR_NO_MATCH
    case "8": // ERROR_RECOGNIZER_BUSY
      return null; // 静音/停顿类：由 listeningState 'stopped' 自动续听
    default:
      return "语音转写失败，请重试";
  }
}

/** 拼接已定稿段与当前 interim，去掉多余空白 (原生按段累积)。 */
function joinText(...parts: string[]): string {
  return parts
    .map((p) => p.trim())
    .filter(Boolean)
    .join(" ");
}

export interface UseVoiceInputOptions {
  /** 转写文本 (追加到现有草稿，不覆盖) —— 由调用方决定如何并入 composer。 */
  onTranscript: (text: string) => void;
}

export interface VoiceInput {
  isSupported: boolean;
  state: VoiceInputState;
  interimText: string;
  duration: number;
  error: string | null;
  start: () => void;
  stop: () => void;
  cancel: () => void;
  toggle: () => void;
  dismissError: () => void;
  isRecording: boolean;
  isProcessing: boolean;
}

export function useVoiceInput({
  onTranscript,
}: UseVoiceInputOptions): VoiceInput {
  const isNative = Capacitor.isNativePlatform();
  const WebSpeechClass = isNative ? null : getWebSpeech();
  // 原生壳假定设备支持 (绝大多数现代 Android/iOS 都有)；不支持时 start 里优雅回退。Web 无 API → 隐藏按钮。
  const isSupported = isNative || WebSpeechClass !== null;

  const [state, setState] = useState<VoiceInputState>("idle");
  const [interimText, setInterimText] = useState("");
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const stateRef = useRef<VoiceInputState>("idle");
  stateRef.current = state;
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  const cancelledRef = useRef(false);
  const intentionalStopRef = useRef(false);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const durationTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const errorTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startTimeRef = useRef(0);

  // Web 引擎状态
  const recognitionRef = useRef<WebSpeechRecognition | null>(null);
  const finalPartsRef = useRef<string[]>([]);
  // 原生引擎状态
  const nativeHandlesRef = useRef<{ remove: () => Promise<void> }[]>([]);
  const nativeAccumRef = useRef("");
  const nativeInterimRef = useRef("");

  const clearTimers = useCallback(() => {
    if (maxTimerRef.current) {
      clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
    if (durationTimerRef.current) {
      clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }
  }, []);

  const resetTranscript = useCallback(() => {
    finalPartsRef.current = [];
    nativeAccumRef.current = "";
    nativeInterimRef.current = "";
    setInterimText("");
    setDuration(0);
  }, []);

  const showError = useCallback((message: string | null) => {
    if (errorTimerRef.current) {
      clearTimeout(errorTimerRef.current);
      errorTimerRef.current = null;
    }
    setError(message);
    if (message) {
      errorTimerRef.current = setTimeout(() => setError(null), ERROR_LINGER_MS);
    }
  }, []);

  const dismissError = useCallback(() => showError(null), [showError]);

  const emitTranscript = useCallback(
    (text: string) => {
      resetTranscript();
      const trimmed = text.trim();
      if (!trimmed) {
        setState("idle");
        return;
      }
      setState("processing");
      onTranscriptRef.current(trimmed);
      setState("idle");
    },
    [resetTranscript],
  );

  // —— 原生引擎 (@capgo/capacitor-speech-recognition) ——

  const teardownNative = useCallback(() => {
    clearTimers();
    const handles = nativeHandlesRef.current;
    nativeHandlesRef.current = [];
    for (const h of handles) void h.remove();
    void SpeechRecognition.removeAllListeners();
  }, [clearTimers]);

  const foldNativeInterim = useCallback(() => {
    if (nativeInterimRef.current.trim()) {
      nativeAccumRef.current = joinText(
        nativeAccumRef.current,
        nativeInterimRef.current,
      );
      nativeInterimRef.current = "";
    }
  }, []);

  const finishNative = useCallback(() => {
    foldNativeInterim();
    const text = nativeAccumRef.current;
    teardownNative();
    emitTranscript(text);
  }, [emitTranscript, foldNativeInterim, teardownNative]);

  const startDurationClock = useCallback(() => {
    startTimeRef.current = Date.now();
    durationTimerRef.current = setInterval(() => {
      setDuration(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
  }, []);

  const stopNative = useCallback(async () => {
    setState("processing");
    try {
      await SpeechRecognition.stop();
    } catch {
      /* already stopped */
    }
    if (cancelledRef.current) return;
    finishNative();
  }, [finishNative]);

  // stop 需被 start 的上限定时器引用，故先定义一个稳定的 stop。
  const stop = useCallback(() => {
    if (stateRef.current !== "recording") return;
    intentionalStopRef.current = true;
    clearTimers();
    if (isNative) {
      void stopNative();
      return;
    }
    const rec = recognitionRef.current;
    if (rec) {
      try {
        rec.stop();
      } catch {
        const text = finalPartsRef.current.join("");
        emitTranscript(text);
      }
    } else {
      emitTranscript(finalPartsRef.current.join(""));
    }
  }, [clearTimers, emitTranscript, isNative, stopNative]);

  const startNative = useCallback(async () => {
    try {
      const perm = await SpeechRecognition.requestPermissions();
      if (perm.speechRecognition !== "granted") {
        showError("麦克风权限被拒绝，请在系统设置中允许访问");
        return;
      }
      const { available } = await SpeechRecognition.available();
      if (!available) {
        showError("此设备不支持语音识别");
        return;
      }
      if (cancelledRef.current) return;

      const language = navigator.language;
      const partial = await SpeechRecognition.addListener(
        "partialResults",
        (event: SpeechRecognitionPartialResultEvent) => {
          const text = event.matches?.[0] ?? "";
          nativeInterimRef.current = text;
          setInterimText(joinText(nativeAccumRef.current, text));
        },
      );
      const listening = await SpeechRecognition.addListener(
        "listeningState",
        (event: SpeechRecognitionListeningEvent) => {
          const stopped =
            event.state === "stopped" || event.status === "stopped";
          if (!stopped) return;
          if (cancelledRef.current || intentionalStopRef.current) return;
          if (stateRef.current !== "recording") return;
          // 意外收束 (通常是静音)：把本段折进累积后重开，等价桌面 onend 的自动重启。
          foldNativeInterim();
          void SpeechRecognition.start({
            language,
            partialResults: true,
          }).catch(() => finishNative());
        },
      );
      const errored = await SpeechRecognition.addListener(
        "error",
        (event: SpeechRecognitionErrorEvent) => {
          if (cancelledRef.current) return;
          const message = mapNativeError(event.code);
          if (!message) return; // 静音/停顿类：交给 listeningState 续听
          teardownNative();
          resetTranscript();
          setState("idle");
          showError(message);
        },
      );
      nativeHandlesRef.current = [partial, listening, errored];

      await SpeechRecognition.start({ language, partialResults: true });
      if (cancelledRef.current) {
        teardownNative();
        return;
      }
      setState("recording");
      startDurationClock();
      maxTimerRef.current = setTimeout(() => stop(), MAX_DURATION_MS);
    } catch {
      teardownNative();
      resetTranscript();
      setState("idle");
      showError("无法启动语音识别，请重试");
    }
  }, [
    finishNative,
    foldNativeInterim,
    resetTranscript,
    showError,
    startDurationClock,
    stop,
    teardownNative,
  ]);

  // —— Web 引擎 (Web Speech API) ——

  const startWeb = useCallback(() => {
    if (!WebSpeechClass) return;
    const rec = new WebSpeechClass();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = navigator.language;

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result[0]?.transcript ?? "";
        if (result.isFinal) {
          finalPartsRef.current.push(transcript);
        } else {
          interim += transcript;
        }
      }
      setInterimText(finalPartsRef.current.join("") + interim);
    };

    rec.onerror = (event) => {
      if (cancelledRef.current) return;
      const message = mapWebError(event.error);
      clearTimers();
      recognitionRef.current = null;
      rec.onresult = null;
      rec.onerror = null;
      rec.onend = null;
      resetTranscript();
      setState("idle");
      if (message) showError(message);
    };

    rec.onend = () => {
      if (cancelledRef.current) return;
      if (intentionalStopRef.current) {
        recognitionRef.current = null;
        emitTranscript(finalPartsRef.current.join(""));
        return;
      }
      // 意外结束 (浏览器超时) → 仍在录音则重开，保住已定稿文本。
      if (recognitionRef.current) {
        try {
          rec.start();
        } catch {
          recognitionRef.current = null;
          emitTranscript(finalPartsRef.current.join(""));
        }
      }
    };

    recognitionRef.current = rec;
    try {
      rec.start();
      setState("recording");
      startDurationClock();
      maxTimerRef.current = setTimeout(() => stop(), MAX_DURATION_MS);
    } catch {
      clearTimers();
      recognitionRef.current = null;
      setState("idle");
      showError("无法启动语音识别，请重试");
    }
  }, [
    WebSpeechClass,
    clearTimers,
    emitTranscript,
    resetTranscript,
    showError,
    startDurationClock,
    stop,
  ]);

  const start = useCallback(() => {
    if (!isSupported || stateRef.current !== "idle") return;
    cancelledRef.current = false;
    intentionalStopRef.current = false;
    resetTranscript();
    showError(null);
    if (isNative) {
      void startNative();
    } else {
      startWeb();
    }
  }, [
    isNative,
    isSupported,
    resetTranscript,
    showError,
    startNative,
    startWeb,
  ]);

  const cancel = useCallback(() => {
    if (stateRef.current !== "recording") return;
    cancelledRef.current = true;
    intentionalStopRef.current = true;
    clearTimers();
    if (isNative) {
      teardownNative();
      void SpeechRecognition.stop().catch(() => {});
    } else {
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      if (rec) {
        rec.onresult = null;
        rec.onerror = null;
        rec.onend = null;
        try {
          rec.abort();
        } catch {
          /* already stopped */
        }
      }
    }
    resetTranscript();
    setState("idle");
  }, [clearTimers, isNative, resetTranscript, teardownNative]);

  const toggle = useCallback(() => {
    if (stateRef.current === "idle") start();
    else if (stateRef.current === "recording") stop();
  }, [start, stop]);

  // 卸载即硬停：直接读 ref 拆除两套引擎 + 定时器，避免离屏后回调继续跑。
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      intentionalStopRef.current = true;
      if (maxTimerRef.current) clearTimeout(maxTimerRef.current);
      if (durationTimerRef.current) clearInterval(durationTimerRef.current);
      if (errorTimerRef.current) clearTimeout(errorTimerRef.current);
      const rec = recognitionRef.current;
      recognitionRef.current = null;
      if (rec) {
        rec.onresult = null;
        rec.onerror = null;
        rec.onend = null;
        try {
          rec.abort();
        } catch {
          /* already stopped */
        }
      }
      const handles = nativeHandlesRef.current;
      nativeHandlesRef.current = [];
      for (const h of handles) void h.remove();
      if (Capacitor.isNativePlatform()) {
        void SpeechRecognition.removeAllListeners();
        void SpeechRecognition.stop().catch(() => {});
      }
    };
  }, []);

  return {
    isSupported,
    state,
    interimText,
    duration,
    error,
    start,
    stop,
    cancel,
    toggle,
    dismissError,
    isRecording: state === "recording",
    isProcessing: state === "processing",
  };
}
