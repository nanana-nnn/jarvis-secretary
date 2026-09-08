import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { Pairing } from "./components/Pairing";
import { claimPairingCode } from "./pairing";
import "./style.css";

document.getElementById("boot-status")?.remove();

// 見た目の確認（`?state=`）はサーバーへ繋がないので、登録を求めない。
// dev / VITE_PREVIEW=1 のビルドでだけ開く口（App.tsx の previewable と同じ条件）
const previewable = import.meta.env.DEV || import.meta.env.VITE_PREVIEW === "1";
const root = ReactDOM.createRoot(document.getElementById("root")!);

// トップレベル await にしない（ビルド対象によっては通らない）。
// 引き換えが終わってから描く。合図が無ければ保存済みトークンがそのまま返る
claimPairingCode().then(token => {
  root.render(<React.StrictMode>{token || previewable ? <App /> : <Pairing />}</React.StrictMode>);
});
