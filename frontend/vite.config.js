import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo, /api se proxea a Django (manage.py runserver en :8000).
// En producción el build (dist/) lo sirve el propio backend: mismo origen, sin CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: true },
});
