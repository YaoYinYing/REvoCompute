import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';
import { resolveConfig } from 'vite';

import { developmentAssetSource } from '../vite.config.js';

describe('development server configuration', () => {
  it('routes APIs and legacy navigation to the same backend without proxying Result routes', async () => {
    const config = await resolveConfig(
      { configFile: resolve(import.meta.dirname, '../vite.config.ts') },
      'serve',
    );
    const proxy = config.server.proxy || {};

    expect(proxy['/compute/api']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/compute/dashboard']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/compute/login']).toMatchObject({ target: 'http://127.0.0.1:8080', changeOrigin: false });
    expect(proxy['/compute/results']).toBeUndefined();
    expect(config.appType).toBe('spa');
  });

  it('serves stable legacy viewer URLs from source while developing', () => {
    expect(developmentAssetSource('/static/app/assets/molecular-viewer.js')).toBe(
      '/static/app/src/features/structure/MolecularViewer.ts',
    );
    expect(developmentAssetSource('/static/app/assets/molecular-viewer.css?v=1')).toBe(
      '/static/app/node_modules/molstar/build/viewer/molstar.css',
    );
    expect(developmentAssetSource('/static/app/assets/result.js')).toBeNull();
  });
});
