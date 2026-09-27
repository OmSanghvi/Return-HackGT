import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server only (no effect on `vite build`): `/api/*` is proxied to the
// backend exactly like vercel.json's rewrite in production, so
// `VITE_SKETCHSCAPE_API_URL=/api npm run dev` works locally without the
// backend's CORS allowlist knowing about localhost. Point it at another
// backend (e.g. http://localhost:8000) with SKETCHSCAPE_DEV_API_PROXY.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const target = env.SKETCHSCAPE_DEV_API_PROXY || 'http://100.63.32.83:8000';
  return {
    plugins: [react()],
    server: { proxy: { '/api': { target, changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') } } },
  };
});
