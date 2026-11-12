import { defineConfig } from 'vite';
import { resolve } from 'node:path';

const serverResources = [
  '/compute/health',
  '/openapi.json',
  '/skills.md',
];

export const createViteConfig = (backend: string, base = '/static/app/') => ({
  base,
  define: {
    // The same immutable identity the server image records, baked into the
    // bundle so the version page can detect a mixed or stale deployment.
    __REVOCOMPUTE_BUILD__: JSON.stringify({
      gitSha: process.env.REVOCOMPUTE_BUILD_GIT_SHA || '',
      builtAt: process.env.REVOCOMPUTE_BUILD_TIME || '',
      baseVersion: process.env.REVOCOMPUTE_BASE_VERSION || '',
    }),
  },
  build: {
    manifest: true,
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: true,
    rollupOptions: {
      input: { app: resolve(import.meta.dirname, 'index.html') },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/compute/api', ...serverResources].map(path => [path, { target: backend, changeOrigin: false }]),
    ),
  },
});

export default defineConfig(({ command }) =>
  createViteConfig(process.env.REVOCOMPUTE_BACKEND_URL || 'http://127.0.0.1:8080', command === 'serve' ? '/' : '/static/app/'),
);
