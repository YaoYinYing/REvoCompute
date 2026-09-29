import { defineConfig, type Plugin } from 'vite';
import { resolve } from 'node:path';
import type { PreRenderedAsset, PreRenderedChunk } from 'rolldown';

const legacyRoutes = [
  '/compute/configuration',
  '/compute/create_task',
  '/compute/dashboard',
  '/compute/health',
  '/compute/login',
  '/compute/logo.svg',
  '/compute/logs',
  '/compute/profile',
  '/compute/register',
  '/compute/reset_password',
  '/compute/terms',
  '/compute/user_control',
  '/compute/user_verify',
  '/favicon.ico',
  '^/static/(?!app(?:/|$))',
];

export const developmentAssetSource = (url: string): string | null => {
  const pathname = url.split('?', 1)[0];
  if (pathname === '/static/app/assets/molecular-viewer.js') {
    return '/static/app/src/features/structure/MolecularViewer.ts';
  }
  if (pathname === '/static/app/assets/molecular-viewer.css') {
    return '/static/app/node_modules/molstar/build/viewer/molstar.css';
  }
  return null;
};

const legacyViewerDevelopmentEntry = (): Plugin => ({
  name: 'revocompute-legacy-viewer-development-entry',
  configureServer(server) {
    server.middlewares.use((request, _response, next) => {
      const source = developmentAssetSource(request.url || '');
      if (source) request.url = source;
      next();
    });
  },
});

export const createViteConfig = (backend: string) => ({
  plugins: [legacyViewerDevelopmentEntry()],
  base: '/static/app/',
  build: {
    manifest: true,
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    cssCodeSplit: true,
    rollupOptions: {
      input: {
        app: resolve(import.meta.dirname, 'index.html'),
        'molecular-viewer': resolve(import.meta.dirname, 'src/features/structure/MolecularViewer.ts'),
      },
      output: {
        entryFileNames: (chunk: PreRenderedChunk) => chunk.name === 'molecular-viewer'
          ? 'assets/molecular-viewer.js'
          : 'assets/[name]-[hash].js',
        assetFileNames: (asset: PreRenderedAsset) => asset.names.some((name: string) => name === 'molecular-viewer.css')
          ? 'assets/molecular-viewer.css'
          : 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ['/compute/api', ...legacyRoutes].map(path => [path, { target: backend, changeOrigin: false }]),
    ),
  },
});

export default defineConfig(
  createViteConfig(process.env.REVOCOMPUTE_BACKEND_URL || 'http://127.0.0.1:8080'),
);
