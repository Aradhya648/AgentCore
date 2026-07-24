"""Inline HTML for the demo-tape director console (dev-only control room)."""

from __future__ import annotations

# HTML/JS blob — line length is not meaningful here.
# ruff: noqa: E501

DIRECTOR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Demo Tape · 控制室</title>
<meta name="director-rev" content="0" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600;700&family=Syne:wght@600;700;800&display=swap" rel="stylesheet" />
<style>
  :root {
    --bg: #eceeea;
    --bg-elev: #f7f8f6;
    --bg-panel: #f3f4f1;
    --bg-input: #ffffff;
    --bg-track: #e4e6e1;
    --line: #c8cbc3;
    --line-soft: #daddd4;
    --text: #1a1c19;
    --muted: #5a5e56;
    --dim: #858a80;
    --amber: #b87a12;
    --amber-dim: #f7ecd4;
    --teal: #1a8f74;
    --teal-dim: #d8efe8;
    --air: #c44a42;
    --air-dim: #f5e0de;
    --danger: #c44a42;
    --seek: #2a7a8c;
    --seek-dim: #d5e8ec;
    --radius: 6px;
    --tap: 44px;
    --font-display: "Syne", "PingFang SC", "Microsoft YaHei", sans-serif;
    --font-body: "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
    --font-mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: var(--font-body);
    font-size: 14px;
    line-height: 1.45;
    color: var(--text);
    min-height: 100vh;
    background:
      radial-gradient(ellipse 90% 60% at 12% -10%, rgba(184, 122, 18, 0.09), transparent 55%),
      radial-gradient(ellipse 70% 50% at 92% 8%, rgba(26, 143, 116, 0.08), transparent 50%),
      radial-gradient(ellipse 50% 40% at 50% 100%, rgba(220, 224, 216, 0.85), transparent 70%),
      var(--bg);
    background-attachment: fixed;
  }
  body::before {
    content: "";
    position: fixed; inset: 0; pointer-events: none; z-index: 0;
    opacity: 0.045;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }
  .shell {
    position: relative; z-index: 1;
    max-width: 1440px; margin: 0 auto;
    padding: 12px 20px 28px;
  }

  /* —— Top bar (masthead) —— */
  .masthead {
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; flex-wrap: wrap;
    margin-bottom: 12px; padding: 10px 0 12px;
    border-bottom: 1px solid var(--line-soft);
  }
  .brand-row {
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap; min-width: 0;
  }
  .masthead h1 {
    margin: 0; font-family: var(--font-display);
    font-size: clamp(18px, 2vw, 22px); font-weight: 800;
    letter-spacing: -0.02em; line-height: 1.1; white-space: nowrap;
  }
  .masthead h1 span { color: var(--dim); font-weight: 700; }
  .tally {
    display: inline-flex; align-items: center; gap: 6px;
  }
  .tally-lamp {
    display: inline-flex; align-items: center; gap: 5px;
    height: 22px; padding: 0 8px;
    border: 1px solid var(--line); border-radius: 2px;
    background: var(--bg-track);
    font-family: var(--font-mono); font-size: 10px; font-weight: 600;
    letter-spacing: 0.06em; color: var(--dim);
  }
  .tally-lamp::before {
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: var(--dim); opacity: 0.45;
  }
  .tally-lamp.on[data-kind="air"] {
    color: var(--air); border-color: rgba(196, 74, 66, 0.45); background: var(--air-dim);
  }
  .tally-lamp.on[data-kind="air"]::before {
    background: var(--air); opacity: 1;
    box-shadow: 0 0 0 0 rgba(196, 74, 66, 0.4);
    animation: air-pulse 1.8s ease-out infinite;
  }
  .tally-lamp.on[data-kind="pause"] {
    color: var(--amber); border-color: rgba(184, 122, 18, 0.45); background: var(--amber-dim);
  }
  .tally-lamp.on[data-kind="pause"]::before { background: var(--amber); opacity: 1; }
  .tally-lamp.on[data-kind="seek"] {
    color: var(--seek); border-color: rgba(42, 122, 140, 0.45); background: var(--seek-dim);
  }
  .tally-lamp.on[data-kind="seek"]::before { background: var(--seek); opacity: 1; }
  .tally-lamp.on[data-kind="err"] {
    color: var(--danger); border-color: rgba(196, 74, 66, 0.5); background: var(--air-dim);
  }
  .tally-lamp.on[data-kind="err"]::before { background: var(--danger); opacity: 1; }
  .masthead-right {
    display: flex; align-items: center; justify-content: flex-end;
    gap: 14px; flex-wrap: wrap;
  }
  .masthead .env {
    font-family: var(--font-mono); font-size: 10px; color: var(--dim);
    letter-spacing: 0.04em;
  }

  /* —— Auth in masthead —— */
  #authPanel { min-width: 0; }
  #authPanel.collapsed .auth-form { display: none; }
  #authPanel .auth-badge {
    display: none; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  #authPanel.collapsed .auth-badge { display: flex; }
  #authPanel:not(.collapsed) {
    margin-top: 4px; padding: 12px 14px;
    background: var(--bg-panel); border: 1px solid var(--line-soft);
    border-radius: var(--radius);
  }
  .masthead:has(#authPanel:not(.collapsed)) {
    align-items: flex-start;
  }
  .masthead:has(#authPanel:not(.collapsed)) .masthead-right {
    flex: 1 1 100%;
    width: 100%;
  }
  .masthead:has(#authPanel:not(.collapsed)) #authPanel {
    width: 100%;
  }
  .conn-pill {
    display: inline-flex; align-items: center; gap: 7px;
    font-size: 12px; font-weight: 600; color: var(--teal);
  }
  .conn-pill .dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--teal);
  }
  .conn-base {
    font-family: var(--font-mono); font-size: 11px; color: var(--muted);
  }

  /* —— Layout —— */
  .deck {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
    gap: 0 24px; align-items: start;
  }
  @media (max-width: 960px) {
    .deck { grid-template-columns: 1fr; gap: 20px; }
    .rail {
      border-left: none; padding-left: 0;
      border-top: 1px solid var(--line-soft); padding-top: 16px;
      position: static;
    }
  }
  .stage { display: flex; flex-direction: column; gap: 0; min-width: 0; }
  .rail {
    border-left: 1px solid var(--line-soft);
    padding-left: 24px; min-height: 160px;
    position: sticky; top: 12px;
  }

  .sect {
    padding: 14px 0;
    border-bottom: 1px solid var(--line-soft);
  }
  .sect:last-child { border-bottom: none; }
  .sect-label {
    margin: 0 0 10px;
    font-family: var(--font-display);
    font-size: 10px; font-weight: 700;
    letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--dim);
  }

  label.field {
    display: block; margin: 0;
    font-size: 10px; font-weight: 500; color: var(--muted);
    letter-spacing: 0.04em;
  }
  label.field > :is(input, select) { margin-top: 3px; }
  input[type=text], input[type=password], input[type=number], select {
    width: 100%; height: var(--tap); padding: 0 10px;
    border: 1px solid var(--line); border-radius: var(--radius);
    background: var(--bg-input); color: var(--text);
    font-family: var(--font-body); font-size: 13px;
  }
  input[type=number] { font-family: var(--font-mono); }
  #cid { font-family: var(--font-mono); font-size: 12px; }
  input:focus, select:focus {
    outline: none;
    border-color: var(--teal);
    box-shadow: inset 0 0 0 1px var(--teal);
  }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end; }
  .row > * { min-width: 0; }
  .grow { flex: 1 1 140px; }

  button, .btn {
    appearance: none; border: 1px solid var(--line);
    background: var(--bg-input); color: var(--text);
    border-radius: var(--radius); min-height: var(--tap);
    padding: 0 12px; font-family: var(--font-body);
    font-size: 13px; font-weight: 600; cursor: pointer;
    transition: border-color 0.12s ease, background 0.12s ease, color 0.12s ease;
  }
  button:hover:not(:disabled) { border-color: #a8aca2; background: #e4e6e1; }
  button:active:not(:disabled) { transform: translateY(1px); }
  button.primary {
    background: var(--teal-dim); border-color: var(--teal); color: var(--teal);
  }
  button.primary:hover:not(:disabled) { background: #c5e6dc; }
  button.ghost { background: transparent; }
  button.active {
    background: var(--amber-dim); border-color: var(--amber); color: var(--amber);
  }
  button:disabled { opacity: 0.4; cursor: not-allowed; }

  /* —— Session strip (one row) —— */
  #sessionCard { padding-top: 10px; padding-bottom: 10px; }
  #sessionCard .sect-label { display: none; }
  .session-strip {
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
  }
  .session-strip select { flex: 1 1 220px; min-width: 160px; height: 36px; }
  .session-strip #cid { flex: 1 1 200px; min-width: 160px; height: 36px; }
  .session-strip #btnRefresh { height: 36px; min-height: 36px; }
  #sessionGuide {
    width: 100%; margin-top: 8px; padding: 8px 10px;
    border-left: 2px solid var(--line); color: var(--muted); font-size: 12px;
  }
  #sessionGuide[hidden] { display: none !important; }
  #sessionGuide strong { color: var(--text); font-weight: 600; }

  /* —— Transport deck (primary surface) —— */
  #transportCard {
    padding: 18px 0 20px;
  }
  .hero {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 12px 20px; align-items: end;
  }
  @media (max-width: 560px) { .hero { grid-template-columns: 1fr; } }
  .hero-state {
    font-family: var(--font-display);
    font-size: clamp(36px, 5.5vw, 56px); font-weight: 800;
    letter-spacing: -0.03em; line-height: 1.02; margin: 0;
    transition: color 0.2s ease;
  }
  .hero-state[data-kind="playing"] {
    color: var(--teal);
    animation: playing-breathe 2.4s ease-in-out infinite;
  }
  .hero-state[data-kind="paused"],
  .hero-state[data-kind="awaiting_paused"] { color: var(--amber); }
  .hero-state[data-kind="awaiting"] { color: var(--amber); opacity: 0.92; }
  .hero-state[data-kind="seeking"] { color: var(--seek); }
  .hero-state[data-kind="idle"],
  .hero-state[data-kind="finished"] { color: var(--muted); }
  .hero-state[data-kind="error"] { color: var(--danger); }
  .hero-meta {
    color: var(--muted); font-size: 12px; margin-top: 8px;
    max-width: 56ch;
  }
  .hero-meta strong { color: var(--text); font-weight: 600; }
  .speed-readout {
    font-family: var(--font-mono);
    font-size: clamp(30px, 4.2vw, 44px); font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: right; color: var(--text);
    line-height: 1; transition: color 0.2s ease, transform 0.2s ease;
  }
  .speed-readout.flash {
    color: var(--amber);
    transform: scale(1.04);
  }
  .speed-readout small {
    display: block; margin-top: 6px;
    font-family: var(--font-body); font-size: 10px;
    font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--dim);
  }

  .transport-bar {
    display: flex; gap: 10px; flex-wrap: wrap;
    align-items: center; margin-top: 20px;
  }
  #btnPlayPause {
    min-width: 148px; min-height: 60px;
    font-family: var(--font-display); font-size: 18px; font-weight: 700;
    border-radius: var(--radius);
  }
  #btnPlayPause.is-playing {
    background: var(--amber-dim); border-color: var(--amber); color: var(--amber);
  }
  #btnPlayPause.is-paused {
    background: var(--teal-dim); border-color: var(--teal); color: var(--teal);
  }
  .speed-presets { display: flex; gap: 4px; flex-wrap: wrap; }
  .speed-presets button {
    min-width: 48px; min-height: 40px; padding: 0 8px;
    font-family: var(--font-mono); font-size: 13px; font-weight: 500;
  }
  .speed-custom { width: 72px; min-height: 40px; height: 40px; }

  /* —— Timeline —— */
  #timelineCard { padding-top: 16px; }
  .time-row {
    display: flex; justify-content: space-between; align-items: baseline;
    font-variant-numeric: tabular-nums; margin-bottom: 4px;
  }
  .time-row .now {
    font-family: var(--font-mono);
    font-size: clamp(30px, 4vw, 40px); font-weight: 600;
    letter-spacing: -0.02em;
  }
  .time-row .dur {
    font-family: var(--font-mono); color: var(--muted); font-size: 14px;
  }
  .scrub-wrap { position: relative; padding: 18px 0 14px; }
  .markers {
    position: absolute; left: 0; right: 0; top: 2px; height: 14px;
    pointer-events: none; /* rail itself passthrough; markers re-enable below */
  }
  .markers .marker {
    pointer-events: auto;
    position: absolute; top: 0; width: 10px; height: 14px;
    padding: 0; min-height: 0; border: none; border-radius: 1px;
    background: transparent; transform: translateX(-5px);
    pointer-events: auto; cursor: pointer;
  }
  .markers .marker::after {
    content: "";
    position: absolute; left: 4px; top: 0; width: 2px; height: 12px;
    background: var(--amber); opacity: 0.65;
  }
  .markers .marker:hover::after {
    opacity: 1; height: 14px; background: var(--seek);
  }
  input[type=range] {
    -webkit-appearance: none; appearance: none;
    width: 100%; height: 36px; background: transparent; margin: 0; padding: 0;
  }
  input[type=range]::-webkit-slider-runnable-track {
    height: 12px; border-radius: 2px;
    background: var(--bg-input); border: 1px solid var(--line);
  }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 18px; height: 22px; border-radius: 2px;
    background: var(--text); border: none; margin-top: -6px; cursor: pointer;
  }
  input[type=range]::-moz-range-track {
    height: 12px; border-radius: 2px;
    background: var(--bg-input); border: 1px solid var(--line);
  }
  input[type=range]::-moz-range-thumb {
    width: 18px; height: 22px; border-radius: 2px;
    background: var(--text); border: none; cursor: pointer;
  }
  .seek-row { margin-top: 2px; }
  .seek-row #btnSeek {
    min-height: 36px; font-size: 12px; font-weight: 500;
    color: var(--muted); background: transparent;
  }
  .seek-hint {
    margin-top: 8px; font-size: 11px; color: var(--dim);
  }

  /* —— Chapters rail —— */
  .chapter-groups {
    display: flex; flex-direction: column; gap: 14px;
    max-height: calc(100vh - 100px); overflow: auto;
    padding-right: 4px;
  }
  .chapter-group h3 {
    margin: 0 0 6px;
    font-family: var(--font-display);
    font-size: 10px; font-weight: 700;
    letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--dim);
  }
  .chapter-wall { display: flex; flex-direction: column; gap: 1px; }
  .chapter-wall button {
    display: grid;
    grid-template-columns: 44px 1fr;
    gap: 8px; align-items: baseline;
    width: 100%; min-height: 34px; padding: 6px 8px;
    text-align: left; font-weight: 500; font-size: 13px;
    background: transparent; border-color: transparent;
    border-radius: 3px;
    transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  }
  .chapter-wall button:hover:not(:disabled) {
    background: var(--bg-input); border-color: var(--line);
  }
  .chapter-wall button .tc {
    font-family: var(--font-mono); font-size: 11px; color: var(--dim);
    font-weight: 500;
  }
  .chapter-wall button .lb {
    color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .chapter-wall button.current {
    background: var(--teal-dim);
    border-color: var(--teal);
    color: var(--text);
  }
  .chapter-wall button.current .tc { color: var(--teal); }
  .chapter-wall button.current .lb { font-weight: 600; }
  .empty-guide {
    padding: 8px 0; color: var(--muted); font-size: 13px;
  }

  /* —— Log —— */
  details.log { margin-top: 2px; }
  details.log summary {
    cursor: pointer; color: var(--dim); font-size: 11px; font-weight: 600;
    letter-spacing: 0.08em; text-transform: uppercase;
    user-select: none; list-style: none;
  }
  details.log summary::-webkit-details-marker { display: none; }
  details.log summary::before { content: "▸ "; }
  details.log[open] summary::before { content: "▾ "; }
  #log {
    margin-top: 8px; max-height: 140px; overflow: auto;
    white-space: pre-wrap;
    font: 12px/1.4 var(--font-mono);
    color: var(--muted); background: var(--bg-elev); padding: 10px;
    border: 1px solid var(--line-soft); border-radius: var(--radius);
  }
  .raw-status {
    margin-top: 8px;
    font: 11px/1.35 var(--font-mono);
    color: var(--dim); white-space: pre-wrap;
    max-height: 90px; overflow: auto; opacity: 0.7;
  }

  .chapter-groups, #log, .raw-status {
    scrollbar-width: thin;
    scrollbar-color: var(--line) transparent;
  }
  .chapter-groups::-webkit-scrollbar,
  #log::-webkit-scrollbar,
  .raw-status::-webkit-scrollbar { width: 8px; height: 8px; }
  .chapter-groups::-webkit-scrollbar-track,
  #log::-webkit-scrollbar-track,
  .raw-status::-webkit-scrollbar-track { background: transparent; }
  .chapter-groups::-webkit-scrollbar-thumb,
  #log::-webkit-scrollbar-thumb,
  .raw-status::-webkit-scrollbar-thumb {
    background: var(--line); border-radius: 4px;
  }

  @keyframes playing-breathe {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.78; }
  }
  @keyframes air-pulse {
    0% { box-shadow: 0 0 0 0 rgba(196, 74, 66, 0.4); }
    70% { box-shadow: 0 0 0 5px rgba(196, 74, 66, 0); }
    100% { box-shadow: 0 0 0 0 rgba(196, 74, 66, 0); }
  }
</style>
</head>
<body>
<div class="shell">
  <header class="masthead">
    <div class="brand-row">
      <h1>Demo Tape <span>· 控制室</span></h1>
      <div class="tally" id="tallyStrip" aria-label="状态灯">
        <span class="tally-lamp" data-kind="air" id="tallyAir">AIR</span>
        <span class="tally-lamp" data-kind="pause" id="tallyPause">PAUSE</span>
        <span class="tally-lamp" data-kind="seek" id="tallySeek">SEEK</span>
        <span class="tally-lamp" data-kind="err" id="tallyErr">ERR</span>
      </div>
    </div>
    <div class="masthead-right">
      <div class="env">DEMO_TAPE_REPLAY_ENABLED</div>
      <section id="authPanel">
        <div class="auth-form">
          <div class="row">
            <label class="field grow">API base
              <input id="base" type="text" placeholder="默认当前 origin" />
            </label>
          </div>
          <div class="row">
            <label class="field grow">用户名
              <input id="user" type="text" value="dev" autocomplete="username" />
            </label>
            <label class="field grow">密码
              <input id="pass" type="password" value="devpassword" autocomplete="current-password" />
            </label>
            <button class="primary" id="btnLogin" type="button">登录</button>
          </div>
        </div>
        <div class="auth-badge">
          <span class="conn-pill"><span class="dot"></span><span id="authBadgeText">已登录</span></span>
          <span class="conn-base" id="baseBadge"></span>
          <button class="ghost" id="btnLogout" type="button">退出 / 改连接</button>
        </div>
      </section>
    </div>
  </header>

  <div class="deck">
    <div class="stage">
      <section class="sect" id="sessionCard">
        <h2 class="sect-label">会话</h2>
        <div class="session-strip">
          <select id="sessionSelect" title="活跃回放"><option value="">选择会话…</option></select>
          <button id="btnRefresh" type="button">刷新</button>
          <input id="cid" type="text" placeholder="conversation_id" spellcheck="false" title="conversation_id" />
        </div>
        <div id="sessionGuide">
          <strong>尚无活跃回放。</strong>
          请先在桌面端用命令面板「演示回放」准备/开播磁带，再点刷新。
          登录后下拉会列出本机进程内正在注入的会话。
        </div>
      </section>

      <section class="sect" id="transportCard">
        <h2 class="sect-label">传输</h2>
        <div class="hero">
          <div>
            <p class="hero-state" id="heroState" data-kind="idle">未连接</p>
            <div class="hero-meta" id="heroMeta">登录并选择会话后开始控制</div>
          </div>
          <div class="speed-readout" id="speedReadout"><span id="speedBig">—</span><small>倍速</small></div>
        </div>
        <div class="transport-bar">
          <button id="btnPlayPause" type="button" disabled>▶ 继续</button>
          <div class="speed-presets" id="speedPresets">
            <button type="button" data-speed="0.5">0.5×</button>
            <button type="button" data-speed="1">1×</button>
            <button type="button" data-speed="2">2×</button>
            <button type="button" data-speed="4">4×</button>
            <button type="button" data-speed="8">8×</button>
          </div>
          <input class="speed-custom" id="speedCustom" type="number" min="0.5" max="8" step="0.1" value="4" title="自定义倍速" />
          <button id="btnSpeedApply" type="button">应用</button>
        </div>
      </section>

      <section class="sect" id="timelineCard">
        <h2 class="sect-label">时间轴</h2>
        <div class="time-row">
          <span class="now" id="tNow">0:00</span>
          <span class="dur" id="tDur">/ 0:00 · —</span>
        </div>
        <div class="scrub-wrap">
          <div class="markers" id="markers"></div>
          <input id="scrub" type="range" min="0" max="0" value="0" step="1" />
        </div>
        <div class="row seek-row">
          <button class="ghost grow" id="btnSeek" type="button">跳到此处</button>
        </div>
        <div class="seek-hint">松开滑块自动 seek · 向后跳 = 重启回放重建画面 · 跨授权卡自动代确认</div>
      </section>

      <section class="sect">
        <details class="log" id="logDetails">
          <summary>操作日志</summary>
          <div id="log"></div>
          <div class="raw-status" id="rawStatus"></div>
        </details>
      </section>
    </div>

    <aside class="rail" id="chaptersCard">
      <h2 class="sect-label">章节</h2>
      <div class="chapter-groups" id="chapters"></div>
    </aside>
  </div>
</div>

<script>
(function () {
  const $ = (id) => document.getElementById(id);

  let token = localStorage.getItem("demo_tape_director_token") || "";
  let chapters = [];
  let lastStatus = null;
  let pollTimer = null;
  let scrubbing = false;

  function baseUrl() {
    const v = $("base").value.trim();
    if (v) return v.replace(/\\/$/, "");
    return location.origin;
  }

  function localTime() {
    return new Date().toLocaleTimeString(undefined, { hour12: false });
  }

  function log(msg) {
    const el = $("log");
    el.textContent = localTime() + "  " + msg + "\\n" + el.textContent;
  }

  function fmtMs(ms) {
    const n = Math.max(0, Math.floor(Number(ms) || 0) / 1000);
    const m = Math.floor(n / 60);
    const s = Math.floor(n % 60);
    return m + ":" + String(s).padStart(2, "0");
  }

  function canPoll() {
    return Boolean(token && $("cid").value.trim());
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startPoll() {
    stopPoll();
    if (!canPoll()) return;
    pollTimer = setInterval(() => { pollStatus().catch(() => {}); }, 400);
  }

  function setAuthUI() {
    const panel = $("authPanel");
    if (token) {
      panel.classList.add("collapsed");
      $("authBadgeText").textContent = "已登录 · " + ($("user").value || "dev");
      $("baseBadge").textContent = baseUrl();
    } else {
      panel.classList.remove("collapsed");
    }
  }

  async function api(path, opts = {}) {
    const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
    if (token) headers["Authorization"] = "Bearer " + token;
    const r = await fetch(baseUrl() + path, Object.assign({}, opts, { headers }));
    if (!r.ok) {
      const t = await r.text();
      throw new Error(r.status + " " + t.slice(0, 200));
    }
    if (r.status === 204) return null;
    const ct = r.headers.get("content-type") || "";
    if (ct.includes("application/json")) return r.json();
    return r.text();
  }

  /** UI-facing transport label — soft_paused overrides bare state when awaiting. */
  function displayTransport(s) {
    if (!s) return { kind: "idle", title: "未连接", detail: "" };
    const soft = !!s.soft_paused;
    const st = String(s.state || "");
    if (st === "error") {
      return { kind: "error", title: "出错", detail: s.error || "" };
    }
    if (st === "finished") {
      return { kind: "finished", title: "已结束", detail: soft ? "导演软暂停仍开着" : "" };
    }
    if (st === "seeking") {
      return {
        kind: soft ? "paused" : "seeking",
        title: soft ? "导演暂停" : "跳转中",
        detail: soft ? "爆发注入已挂起 · 点继续恢复" : "爆发注入中",
      };
    }
    if (st === "awaiting_interaction") {
      if (soft) {
        return {
          kind: "awaiting_paused",
          title: "等待授权卡 · 已暂停",
          detail: "真交互停在授权卡；导演节拍已冻结（state 仍为 awaiting_interaction）",
        };
      }
      return {
        kind: "awaiting",
        title: "等待授权卡",
        detail: "桌面点「授权开赛」，或向前 seek 自动代确认",
      };
    }
    if (st === "paused" || soft) {
      return { kind: "paused", title: "导演暂停", detail: "节拍器已冻结 · 点继续恢复" };
    }
    if (st === "playing") {
      return { kind: "playing", title: "播放中", detail: (s.chapter_label || "") };
    }
    return { kind: "idle", title: st || "空闲", detail: s.chapter_label || "" };
  }

  function updateTally(kind) {
    const air = $("tallyAir");
    const pause = $("tallyPause");
    const seek = $("tallySeek");
    const err = $("tallyErr");
    if (!air) return;
    air.classList.toggle("on", kind === "playing");
    pause.classList.toggle("on", kind === "paused" || kind === "awaiting" || kind === "awaiting_paused");
    seek.classList.toggle("on", kind === "seeking");
    err.classList.toggle("on", kind === "error");
  }

  function isEffectivelyPaused(s) {
    if (!s) return true;
    if (s.soft_paused) return true;
    return s.state === "paused" || s.state === "awaiting_interaction" || s.state === "finished" || s.state === "idle";
  }

  function updatePlayPauseButton(s) {
    const btn = $("btnPlayPause");
    const has = canPoll();
    btn.disabled = !has;
    if (!has) {
      btn.textContent = "▶ 继续";
      btn.className = "";
      return;
    }
    const paused = isEffectivelyPaused(s);
    // awaiting without soft_pause: still "waiting for card", resume is soft-only —
    // show 继续 only when soft_paused or state===paused; for pure awaiting show 暂停 to freeze metronome.
    if (s && s.state === "awaiting_interaction" && !s.soft_paused) {
      btn.textContent = "⏸ 暂停节拍";
      btn.className = "is-playing";
      btn.dataset.action = "pause";
      return;
    }
    if (paused) {
      btn.textContent = "▶ 继续";
      btn.className = "is-paused";
      btn.dataset.action = "resume";
    } else {
      btn.textContent = "⏸ 暂停";
      btn.className = "is-playing";
      btn.dataset.action = "pause";
    }
  }

  function highlightSpeed(speed) {
    const n = Number(speed);
    $("speedCustom").value = String(n);
    $("speedBig").textContent = Number.isFinite(n) ? n + "×" : "—";
    const readout = $("speedReadout");
    if (readout) {
      readout.classList.remove("flash");
      void readout.offsetWidth;
      readout.classList.add("flash");
      clearTimeout(highlightSpeed._t);
      highlightSpeed._t = setTimeout(() => readout.classList.remove("flash"), 280);
    }
    document.querySelectorAll("#speedPresets button").forEach((b) => {
      b.classList.toggle("active", Number(b.dataset.speed) === n);
    });
  }

  function renderHero(s) {
    const d = displayTransport(s);
    const el = $("heroState");
    el.textContent = d.title;
    el.dataset.kind = d.kind;
    updateTally(d.kind);
    const parts = [];
    if (s) {
      parts.push("章节 <strong>" + (s.chapter_label || "—") + "</strong>");
      parts.push("事件 <strong>" + (s.event_index ?? "—") + "</strong>/" + (s.event_count ?? "—"));
      if (s.live) parts.push("live");
      if (s.soft_paused) parts.push("soft_paused");
      if (d.detail) parts.push(d.detail);
    } else {
      parts.push(d.detail || "登录并选择会话后开始控制");
    }
    $("heroMeta").innerHTML = parts.join(" · ");
    updatePlayPauseButton(s);
    if (s) highlightSpeed(s.speed);
  }

  function renderMarkers() {
    const box = $("markers");
    box.innerHTML = "";
    const dur = Number($("scrub").max) || 0;
    if (!dur || !chapters.length) return;
    for (const ch of chapters) {
      const pct = Math.min(100, Math.max(0, (ch.t_ms / dur) * 100));
      const sp = document.createElement("button");
      sp.type = "button";
      sp.className = "marker";
      sp.style.left = pct + "%";
      sp.title = ch.label + " · " + fmtMs(ch.t_ms);
      sp.setAttribute("aria-label", "跳到章节 " + ch.label);
      sp.onclick = () => seekChapter(ch.id).catch((e) => log(String(e)));
      box.appendChild(sp);
    }
  }

  function groupChapters(list) {
    const groups = [];
    const ensure = (title) => {
      let g = groups.find((x) => x.title === title);
      if (!g) { g = { title, items: [] }; groups.push(g); }
      return g;
    };
    for (const ch of list) {
      if (ch.id === "opening") ensure("开场").items.push(ch);
      else if (ch.id === "team_preview") ensure("组队授权").items.push(ch);
      else if (ch.id === "verdict") ensure("终审").items.push(ch);
      else {
        const m = /^r(\\d+)_/.exec(ch.id);
        if (m) ensure("第 " + m[1] + " 轮").items.push(ch);
        else ensure("其他").items.push(ch);
      }
    }
    return groups;
  }

  function renderChapters(currentLabel) {
    const root = $("chapters");
    root.innerHTML = "";
    if (!chapters.length) {
      root.innerHTML = '<div class="empty-guide">选择会话后加载章节表</div>';
      return;
    }
    for (const g of groupChapters(chapters)) {
      const sec = document.createElement("div");
      sec.className = "chapter-group";
      const h = document.createElement("h3");
      h.textContent = g.title;
      sec.appendChild(h);
      const wall = document.createElement("div");
      wall.className = "chapter-wall";
      for (const ch of g.items) {
        const b = document.createElement("button");
        b.type = "button";
        const tc = document.createElement("span");
        tc.className = "tc";
        tc.textContent = fmtMs(ch.t_ms);
        const lb = document.createElement("span");
        lb.className = "lb";
        lb.textContent = ch.label;
        b.appendChild(tc);
        b.appendChild(lb);
        b.title = ch.label + " · " + fmtMs(ch.t_ms) + " · #" + ch.event_index;
        if (currentLabel && ch.label === currentLabel) b.classList.add("current");
        b.onclick = () => seekChapter(ch.id);
        wall.appendChild(b);
      }
      sec.appendChild(wall);
      root.appendChild(sec);
    }
  }

  function applyStatus(s) {
    lastStatus = s;
    renderHero(s);
    if (s.duration_ms != null) {
      $("scrub").max = String(s.duration_ms);
      renderMarkers();
    }
    if (!scrubbing) $("scrub").value = String(s.t_ms || 0);
    $("tNow").textContent = fmtMs(s.t_ms || 0);
    $("tDur").textContent = "/ " + fmtMs(s.duration_ms || 0) + " · " + (s.chapter_label || "—");
    renderChapters(s.chapter_label || "");
    $("rawStatus").textContent = JSON.stringify(s, null, 2);
  }

  async function login() {
    const body = { username: $("user").value, password: $("pass").value };
    const data = await api("/v1/auth/token", { method: "POST", body: JSON.stringify(body) });
    token = data.access_token;
    localStorage.setItem("demo_tape_director_token", token);
    setAuthUI();
    log("登录成功");
    await refreshSessions();
    startPoll();
  }

  function logout() {
    token = "";
    localStorage.removeItem("demo_tape_director_token");
    stopPoll();
    setAuthUI();
    lastStatus = null;
    renderHero(null);
    log("已退出");
  }

  async function refreshSessions() {
    if (!token) return;
    const data = await api("/v1/demo-tape/director/sessions");
    const sel = $("sessionSelect");
    const prev = $("cid").value.trim();
    sel.innerHTML = '<option value="">选择会话…</option>';
    const sessions = data.sessions || [];
    for (const s of sessions) {
      const opt = document.createElement("option");
      opt.value = s.conversation_id;
      opt.textContent = (s.tape_id || "?") + " · " + s.conversation_id.slice(0, 8) + " · " + s.state + " · " + (s.speed || "?") + "×";
      sel.appendChild(opt);
    }
    $("sessionGuide").hidden = sessions.length > 0;
    if (prev && sessions.some((s) => s.conversation_id === prev)) {
      sel.value = prev;
    } else if (sessions[0]) {
      $("cid").value = sessions[0].conversation_id;
      sel.value = sessions[0].conversation_id;
      await loadChapters();
      startPoll();
    } else {
      stopPoll();
    }
  }

  async function loadChapters() {
    const cid = $("cid").value.trim();
    if (!cid || !token) return;
    const data = await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/chapters");
    chapters = data.chapters || [];
    const dur = chapters.reduce((m, c) => Math.max(m, c.t_ms || 0), 0);
    if (dur > 0) {
      $("scrub").max = String(Math.max(Number($("scrub").max) || 0, dur));
    }
    renderMarkers();
    renderChapters(lastStatus && lastStatus.chapter_label);
  }

  async function pollStatus() {
    if (!canPoll()) return;
    try {
      const s = await api("/v1/demo-tape/director/" + encodeURIComponent($("cid").value.trim()) + "/status");
      applyStatus(s);
    } catch (e) {
      $("rawStatus").textContent = String(e);
    }
  }

  async function togglePlayPause() {
    const cid = $("cid").value.trim();
    if (!cid) return;
    const action = $("btnPlayPause").dataset.action || "resume";
    if (action === "pause") {
      await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/pause", { method: "POST", body: "{}" });
      log("暂停");
    } else {
      await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/resume", { method: "POST", body: "{}" });
      log("继续");
    }
    await pollStatus();
  }

  async function setSpeed(speed) {
    const cid = $("cid").value.trim();
    if (!cid) return;
    const n = Math.max(0.5, Math.min(8, Number(speed)));
    await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/speed", {
      method: "POST", body: JSON.stringify({ speed: n }),
    });
    log("倍速 " + n + "×");
    highlightSpeed(n);
    await pollStatus();
  }

  function snapTms(raw) {
    const t = Number(raw);
    if (!chapters.length) return t;
    // Prefer nearest event boundary among chapter marks + current scrub neighbors via chapter t_ms.
    // Full event snap is server-side on seek; UI snaps to nearest chapter tick for feel,
    // then server re-snaps to event boundary.
    let best = t;
    let bestDist = Infinity;
    for (const ch of chapters) {
      const d = Math.abs(ch.t_ms - t);
      if (d < bestDist) { bestDist = d; best = ch.t_ms; }
    }
    // If very close to a chapter mark (< 2s), snap to it; else keep scrub value (server snaps).
    if (bestDist <= 2000) return best;
    return t;
  }

  async function seek() {
    const cid = $("cid").value.trim();
    if (!cid) return;
    const t_ms = snapTms($("scrub").value);
    $("scrub").value = String(t_ms);
    await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/seek", {
      method: "POST", body: JSON.stringify({ t_ms: Number(t_ms) }),
    });
    log("seek " + fmtMs(t_ms));
    await pollStatus();
  }

  async function seekChapter(id) {
    const cid = $("cid").value.trim();
    if (!cid) return;
    await api("/v1/demo-tape/director/" + encodeURIComponent(cid) + "/seek", {
      method: "POST", body: JSON.stringify({ chapter_id: id }),
    });
    log("章节 " + id);
    await pollStatus();
  }

  // Wire
  $("btnLogin").onclick = () => login().catch((e) => log(String(e)));
  $("btnLogout").onclick = () => logout();
  $("btnRefresh").onclick = () => refreshSessions().catch((e) => log(String(e)));
  $("btnPlayPause").onclick = () => togglePlayPause().catch((e) => log(String(e)));
  $("btnSpeedApply").onclick = () => setSpeed($("speedCustom").value).catch((e) => log(String(e)));
  $("btnSeek").onclick = () => seek().catch((e) => log(String(e)));
  document.querySelectorAll("#speedPresets button").forEach((b) => {
    b.onclick = () => setSpeed(b.dataset.speed).catch((e) => log(String(e)));
  });
  $("sessionSelect").onchange = () => {
    if ($("sessionSelect").value) {
      $("cid").value = $("sessionSelect").value;
      loadChapters().then(() => startPoll()).catch((e) => log(String(e)));
    } else {
      stopPoll();
    }
  };
  $("cid").onchange = () => {
    if (canPoll()) {
      loadChapters().then(() => startPoll()).catch((e) => log(String(e)));
    } else {
      stopPoll();
    }
  };
  $("scrub").addEventListener("pointerdown", () => { scrubbing = true; });
  $("scrub").addEventListener("pointerup", () => {
    scrubbing = false;
    const snapped = snapTms($("scrub").value);
    $("scrub").value = String(snapped);
    $("tNow").textContent = fmtMs(snapped);
    if (canPoll()) seek().catch((e) => log(String(e)));
  });
  $("scrub").addEventListener("pointercancel", () => { scrubbing = false; });
  $("scrub").addEventListener("input", () => {
    $("tNow").textContent = fmtMs($("scrub").value);
  });

  // Live-reload: DEMO_TAPE_REPLAY_ENABLED disables uvicorn WatchFiles, so poll
  // file mtime rev and soft-reload this tab when director_page.py changes.
  (function liveReload() {
    const meta = document.querySelector('meta[name="director-rev"]');
    const mine = meta && meta.getAttribute("content");
    if (!mine || mine === "0") return;
    let busy = false;
    setInterval(() => {
      if (busy) return;
      busy = true;
      fetch(location.origin + "/v1/demo-tape/director/rev", { cache: "no-store" })
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (j && j.rev != null && String(j.rev) !== String(mine)) {
            location.reload();
          }
        })
        .catch(() => {})
        .finally(() => { busy = false; });
    }, 1500);
  })();

  // Init — no poll until logged in + session selected
  $("base").value = "";
  $("base").placeholder = location.origin || "http://localhost:8000";
  setAuthUI();
  renderHero(null);
  renderChapters("");
  $("sessionGuide").hidden = false;
  if (token) {
    refreshSessions().catch(() => {});
    if ($("cid").value.trim()) {
      loadChapters().catch(() => {});
      startPoll();
    }
  }
})();
</script>
</body>
</html>
"""
