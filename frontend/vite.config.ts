import { defineConfig } from 'vite';
import { resolve } from 'node:path';

const legacyRoutes = [
  '/compute/configuration',
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

export const createViteConfig = (backend: string) => ({
  base: '/static/app/',
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
      ['/compute/api', ...legacyRoutes].map(path => [path, { target: backend, changeOrigin: false }]),
    ),
  },
});

export default defineConfig(
  createViteConfig(process.env.REVOCOMPUTE_BACKEND_URL || 'http://127.0.0.1:8080'),
);
