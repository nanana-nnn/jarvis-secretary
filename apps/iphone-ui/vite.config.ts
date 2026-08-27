import fs from "node:fs";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const root = path.resolve(import.meta.dirname, "../..");
  const env = loadEnv(mode, root, "");
  const cert = path.resolve(root, env.TLS_CERT || "certs/lan.crt");
  const key = path.resolve(root, env.TLS_KEY || "certs/lan.key");
  const https = fs.existsSync(cert) && fs.existsSync(key) ? { cert: fs.readFileSync(cert), key: fs.readFileSync(key) } : undefined;
  const host = env.HOST || "127.0.0.1";
  const proxy = {
    "/ws": {
      target: `wss://${host}:${env.PORT || "8787"}`,
      ws: true,
      secure: false,
    },
  };
  return {
    envDir: root,
    plugins: [react()],
    server: {
      host,
      port: 5173,
      https,
      proxy,
    },
    preview: {
      host,
      port: 5173,
      https,
      proxy,
    },
  };
});
