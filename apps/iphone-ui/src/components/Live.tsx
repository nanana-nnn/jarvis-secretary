/**
 * 3段目。sysmon では tty-clock が入っていた枠。
 *
 * 1段目の fastfetch が「再起動まで変わらない事実」なのに対して、ここは
 * 「今どうなっているか」だけを出す。**すべてサーバーの実測値**で、
 * 飾りで点いているアイコンは1つも無い（AI_RULES「出典が言えないことを書かない」）。
 *
 * - alive … プロセスが在る（/proc を名前で走査）
 * - busy  … CPU時間が伸びている＝処理中（前回観測との差分。初回は必ず false）
 * - vault … git の未コミット件数。数えられなかったときは -1 で、0 と偽らない
 * - phone … WebSocket で実際に繋がっている台数
 */

export type AppState = { alive: boolean; busy: boolean };
export type LiveFacts = {
  apps: Record<string, AppState>;
  vault: { tracked: boolean; dirty: number };
  phones: number;
};

// アイコンは Nerd Font（同梱サブセット）。名前は app.py の WATCHED と対応する。
// コードポイントは記憶で書かない。必ず描いて字を確かめてから入れる
// （2026-08-31、md-brain のつもりが再生ボタン、sparkle のつもりが車になった）。
// 2026-08-31 追記: Nerd Font に本物のロゴが入っていた。近いもので代用しない。
// custom-obsidian / cod-openai(Codex は OpenAI) / cod-claude / fa-chrome はすべて実ロゴ
const APPS: { key: string; icon: string; label: string }[] = [
  { key: "obsidian", icon: "\ue6bb", label: "obsidian" },
  { key: "codex", icon: "\uec81", label: "codex" },
  { key: "claude", icon: "\uec82", label: "claude" },
  { key: "chrome", icon: "\uf268", label: "chrome" },
  { key: "term", icon: "\uea85", label: "terminal" },
];

const PHONE = "\u{f011c}";
const GIT = "\ue702";

// state は表示名（"STANDBY" など）。状態機械の値そのものではない
export function Live({ state, code, live }: { state: string; code: string; live: LiveFacts }) {
  // SNS に上げた小さい画像でも何のアイコンか分かるよう、下に名前を添える
  const dots = APPS.map(({ key, icon, label }) => {
    const app: AppState = live.apps[key] ?? { alive: false, busy: false };
    const status = app.busy ? "busy" : app.alive ? "alive" : "off";
    return <span key={key} className={`dot ${status}`} title={`${label}: ${status}`}>
      <i>{icon}</i><b>{label}</b>
    </span>;
  });

  // 台数と件数は数えられたときだけ出す。分からないものは「?」にして 0 と書かない
  const vault = !live.vault.tracked ? "untracked"
    : live.vault.dirty < 0 ? "?"
    : live.vault.dirty === 0 ? "clean"
    : `${live.vault.dirty} dirty`;

  return <section className="live panel">
    <h1>{state}</h1>
    <small>{code}</small>
    <div className="dots">{dots}</div>
    <div className="live-meta">
      <span className={live.phones > 0 ? "on" : ""}>{PHONE} {live.phones}</span>
      <span className={live.vault.dirty > 0 ? "on" : ""}>{GIT} {vault}</span>
    </div>
  </section>;
}
