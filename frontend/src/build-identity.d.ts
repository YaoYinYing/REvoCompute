/* Injected by Vite's `define`; absent in builds that do not bake identity. */
interface REvoComputeBuildIdentity {
  gitSha: string;
  builtAt: string;
  baseVersion: string;
}

declare const __REVOCOMPUTE_BUILD__: REvoComputeBuildIdentity | undefined;
