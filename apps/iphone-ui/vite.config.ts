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
  const api = `https://${host}:${env.PORT || "8787"}`;
  const proxy = {
    "/ws": {
      target: `wss://${host}:${env.PORT || "8787"}`,
      ws: true,
      secure: false,
    },
    // 壁紙はサーバーが縮めて配る。ここを通さないとプレビューで 404 になる
    "/wallpaper.webp": { target: api, secure: false, changeOrigin: true },
    // 壁紙スライダーのサムネイル（2026-09-05）。**末尾の s を忘れないこと。**
    // 上の "/wallpaper.webp" は "/wallpapers/..." には当たらないので、ここが
    // 無いと画像だけ Vite の 404 になる。切り替え自体は WebSocket 経由なので
    // 動いてしまい、「壁紙は変わるのにスライダーに何も出ない」という
    // 食い違いになる（実機で実際にそうなった）
    "/wallpapers": { target: api, secure: false, changeOrigin: true },
    // 承認／却下は同一オリジンの相対URLで呼ぶ。iPhoneが5173へ送った
    // POSTをFastAPIへ中継しないと、承認画面だけがViteの404になる。
    "/jobs": { target: api, secure: false, changeOrigin: true },
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
