export type ReleaseArtifacts = {
  version: string;
  releaseNotesUrl: string;
  winUrl: string;
  winFilename: string;
  macUrl: string;
  macFilename: string;
  androidUrl: string;
  androidFilename: string;
  androidVersion: string;
};

export const DESKTOP_RELEASE_API = "/api/desktop-release" as const;
