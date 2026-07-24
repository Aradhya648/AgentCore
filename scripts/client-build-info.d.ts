export function readClientBuildInfo(packageJsonUrl: URL): {
  version: string;
  gitSha: string;
};

export function viteClientBuildDefine(
  packageJsonUrl: URL,
): Record<string, string>;
