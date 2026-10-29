import { Agent } from "node:http";
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
        // A fresh connection per request. With Node's default keep-alive
        // agent, some responses (seen with the ~0.5-2 MB raster lists) were
        // reset or never delivered although the backend had answered 200 --
        // the map view then stayed empty.
        agent: new Agent({ keepAlive: false }),
      },
    },
  },
});
