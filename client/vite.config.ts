import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "VITE_");

  return {
    plugins: [react()],
    server: {
      host: true,
      proxy: {
        "/api": env.VITE_API_PROXY_TARGET ?? "http://localhost:3001",
        "/ws": {
          target: env.VITE_WS_PROXY_TARGET ?? "ws://localhost:3001",
          ws: true,
        },
      },
    },
  };
});
