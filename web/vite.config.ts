import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite build + dev-server config.
//
// In production the app is served same-origin behind the Caddy reverse proxy, so
// it calls relative `/api` and `/tiles` paths (see src/config.ts). In local dev
// (`npm run dev`, port 5173) we proxy those same paths to the API and Martin so
// the front end code is identical in both environments.
//
// Override the upstream targets with VITE_DEV_API_TARGET / VITE_DEV_TILES_TARGET
// if you run the API or Martin on non-default ports.
export default defineConfig(({ mode }) => {
  const apiTarget = process.env.VITE_DEV_API_TARGET ?? 'http://localhost:8000';
  const tilesTarget = process.env.VITE_DEV_TILES_TARGET ?? 'http://localhost:3000';
  return {
    plugins: [react()],
    build: {
      // Emit a source map so the handover maintainer can debug the built bundle.
      sourcemap: mode !== 'production',
      outDir: 'dist',
    },
    server: {
      port: 5173,
      proxy: {
        // Strip the /api prefix when forwarding to the FastAPI service.
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
        // Strip the /tiles prefix when forwarding to Martin.
        '/tiles': {
          target: tilesTarget,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/tiles/, ''),
        },
      },
    },
  };
});
