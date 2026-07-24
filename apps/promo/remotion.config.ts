import path from "path";
import { Config } from "@remotion/cli/config";
import { enableTailwind } from "@remotion/tailwind-v4";
import type { Compiler } from "webpack";

const DESKTOP_RENDERER = path.resolve(
  process.cwd(),
  "../desktop/src/renderer",
);
const DESKTOP_SHARED = path.resolve(process.cwd(), "../desktop/src/shared");
const MOBILE_SRC = path.resolve(process.cwd(), "../mobile/src");
const MOBILE_MARKER = `${path.sep}mobile${path.sep}src${path.sep}`;
const PACKAGES = path.resolve(process.cwd(), "../../packages");
const OWN_MODULES = path.resolve(process.cwd(), "node_modules");

/** Route `@/…` to mobile/src when the importing module lives under apps/mobile. */
class MobileContextAliasPlugin {
  apply(compiler: Compiler) {
    compiler.hooks.normalModuleFactory.tap(
      "MobileContextAliasPlugin",
      (nmf) => {
        nmf.hooks.beforeResolve.tap("MobileContextAliasPlugin", (data) => {
          if (!data) return;
          const request = data.request;
          if (!request?.startsWith("@/")) return;
          const issuer = data.contextInfo?.issuer ?? "";
          if (!issuer.includes(MOBILE_MARKER)) return;
          data.request = path.join(MOBILE_SRC, request.slice(2));
        });
      },
    );
  }
}

Config.overrideWebpackConfig((currentConfiguration) => {
  const withTailwind = enableTailwind(currentConfiguration);
  return {
    ...withTailwind,
    plugins: [...(withTailwind.plugins ?? []), new MobileContextAliasPlugin()],
    resolve: {
      ...withTailwind.resolve,
      alias: {
        ...(withTailwind.resolve?.alias ?? {}),
        "@": DESKTOP_RENDERER,
        "@shared": DESKTOP_SHARED,
        "@mobile": MOBILE_SRC,
        "@agentcore/contract-types": path.join(
          PACKAGES,
          "contract-types/src/index.ts",
        ),
        "@agentcore/protocol-conformance/projectedTurn": path.join(
          PACKAGES,
          "protocol-conformance/src/projectedTurn.ts",
        ),
        "@agentcore/protocol-conformance$": path.join(
          PACKAGES,
          "protocol-conformance/src/index.ts",
        ),
        "@agentcore/design-tokens": path.join(PACKAGES, "design-tokens"),
        // Force all React/xyflow to resolve from promo's node_modules to
        // prevent context splitting when importing desktop components.
        react: path.resolve(OWN_MODULES, "react"),
        "react-dom": path.resolve(OWN_MODULES, "react-dom"),
        "@xyflow/react": path.resolve(OWN_MODULES, "@xyflow/react"),
      },
    },
  };
});
