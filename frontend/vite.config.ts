import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Normal use: `npm run build` and the backend serves dist/ together with the API on
// http://localhost:6010 (one port, started by "Start Line Monitor.bat").
// Development only: `npm run dev` gives hot reload on http://localhost:6012 and proxies to the backend.
// Port 6002 is used by another project, so it is deliberately avoided.
const BACKEND_PORT = 6010;
const DEV_PORT = 6012;
const proxy = {
  '/api': { target: `http://127.0.0.1:${BACKEND_PORT}`, changeOrigin: true },
  '/ws': { target: `ws://127.0.0.1:${BACKEND_PORT}`, ws: true, changeOrigin: true },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: DEV_PORT,
    host: '127.0.0.1',
    strictPort: true,
    proxy,
  },
  preview: {
    port: DEV_PORT,
    host: '127.0.0.1',
    strictPort: true,
    proxy,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
});
