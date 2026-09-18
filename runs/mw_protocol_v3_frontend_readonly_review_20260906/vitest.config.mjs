import { defineConfig } from '../../frontend/node_modules/vitest/dist/config.js';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('.', import.meta.url));
export default defineConfig({
  root,
  cacheDir: `${root}/cache`,
  resolve: { alias: { react: fileURLToPath(new URL('../../frontend/node_modules/react', import.meta.url)) } },
  esbuild: { jsx: 'automatic' },
  test: { environment: 'jsdom', include: ['*.test.jsx'] },
});
