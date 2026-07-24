/**
 * Shared Vite plugin — inject a Content-Security-Policy <meta> into index.html.
 * Used by the web clients (mobile / admin). The desktop renderer ships its CSP as an
 * app:// response HEADER instead (apps/desktop/src/main/index.ts).
 *
 * SECURITY (XSS-001 前端XSS·纵深 CSP) — 最正确设计，非便利妥协:
 *  - PROD (build): 严格 `script-src 'self'`，不放 'unsafe-eval' / 'unsafe-inline'。因为 mermaid
 *    图表源是【攻击者可影响】的（模型 / 间接注入可吐 ```mermaid 块），全局 'unsafe-eval' 会把
 *    「解析图表」变成主源里的代码执行原语，所以绝不全局放开 eval。实测打包产物证明严格策略可行：
 *    mermaid v11 把每种图表当普通 dynamic import() 的 ES chunk 从 'self' 加载（script-src 'self'
 *    已覆盖），无 new Worker / createObjectURL / 真 eval；唯一 Function 构造器用法是 lodash 取全局的
 *    `Function("return this")()`，浏览器里被 `self` 短路、不执行。另一前提：关掉 Vite 的 modulepreload
 *    polyfill（否则它注入一段 inline <script>，会被 script-src 'self' 拦掉）。
 *  - DEV (serve): 只注入 object-src/base-uri 子集。dev 下 @vitejs/plugin-react 会注入 inline 的
 *    React Refresh preamble、Vite 客户端走 HMR inline 脚本——强 script-src 会打断热更。脚本注入
 *    的收口只在打包产物（prod）需要。
 *  - worker-src 'self' blob': 前瞻防御。当前 mermaid 不开 worker，但若未来版本把解析挪进 Worker，
 *    动态能力留在 worker 边界内，仍不必污染主文档 script-src。
 *  - style-src 保留 'unsafe-inline'：React / Tailwind / KaTeX 用 style【属性】，CSP 的 nonce/hash
 *    管不到 style 属性；样式注入风险远低于脚本。
 *  - meta 不放 frame-ancestors（在 <meta> 下无效且会告警）；form-action 'self' 在 meta 有效。
 *
 * 兜底阶梯（若未来 mermaid 改为主线程 eval 而报错）: 升级为 mermaid securityLevel:'sandbox'
 * （沙箱 iframe 隔离其动态代码），而【绝不】给 script-src 加回 'unsafe-eval'。
 */

const PROD_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "worker-src 'self' blob:",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",
  "font-src 'self' data:",
  // connect-src stays broad: the API base origin is configured at runtime (cloud https /
  // self-host http://localhost) and SSE/websocket ride it — script-src is the XSS containment.
  "connect-src 'self' https: http: ws: wss:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const DEV_CSP = ["object-src 'none'", "base-uri 'self'"].join("; ");

export function viteCspPlugin() {
  return {
    name: "agentcore-csp",
    transformIndexHtml(html, ctx) {
      const content = ctx.server ? DEV_CSP : PROD_CSP;
      return {
        html,
        tags: [
          {
            tag: "meta",
            attrs: { "http-equiv": "Content-Security-Policy", content },
            injectTo: "head-prepend",
          },
        ],
      };
    },
  };
}
