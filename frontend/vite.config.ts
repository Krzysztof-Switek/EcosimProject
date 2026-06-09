import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api -> FastAPI backend (default :8000), so the
// frontend can use same-origin relative URLs and avoid CORS entirely.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
